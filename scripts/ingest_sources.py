#!/usr/bin/env python3
"""Fetch active GovLens sources and store raw content with audit metadata."""

from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg.rows import dict_row


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"
DEFAULT_RAW_DIR = "data/raw"
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "GovLens/0.1 public-document-ingestion"


@dataclass
class FetchResult:
    status: str
    http_status: int | None = None
    content_hash: str | None = None
    object_path: str | None = None
    error_message: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch active sources from the GovLens source registry."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--raw-dir",
        default=os.environ.get("GOVLENS_RAW_DIR", DEFAULT_RAW_DIR),
        help="Directory where raw fetched content is stored.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of active sources to fetch.",
    )
    return parser.parse_args()


def content_extension(source: dict[str, Any], content_type: str | None) -> str:
    if source["source_type"] == "pdf":
        return ".pdf"
    if source["source_type"] == "csv":
        return ".csv"
    if source["source_type"] == "api":
        return ".json"
    if content_type and "html" in content_type:
        return ".html"

    path = urlparse(source["source_url"]).path
    suffix = Path(path).suffix
    return suffix if suffix else ".bin"


def write_raw_object(
    raw_dir: Path,
    source: dict[str, Any],
    content_hash: str,
    extension: str,
    content: bytes,
) -> str:
    source_dir = raw_dir / str(source["source_id"])
    source_dir.mkdir(parents=True, exist_ok=True)

    object_path = source_dir / f"{content_hash}{extension}"
    object_path.write_bytes(content)

    return str(object_path)


def fetch_source(client: httpx.Client, raw_dir: Path, source: dict[str, Any]) -> FetchResult:
    try:
        response = client.get(source["source_url"])
        response.raise_for_status()

        content = response.content
        content_hash = hashlib.sha256(content).hexdigest()

        if source["current_hash"] == content_hash:
            return FetchResult(
                status="unchanged",
                http_status=response.status_code,
                content_hash=content_hash,
            )

        extension = content_extension(source, response.headers.get("content-type"))
        object_path = write_raw_object(raw_dir, source, content_hash, extension, content)

        return FetchResult(
            status="success",
            http_status=response.status_code,
            content_hash=content_hash,
            object_path=object_path,
        )
    except Exception as error:
        return FetchResult(status="failed", error_message=str(error))


def create_ingestion_run(conn: psycopg.Connection, source_count: int) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs (source_count)
            VALUES (%s)
            RETURNING run_id
            """,
            (source_count,),
        )
        return str(cur.fetchone()["run_id"])


def load_active_sources(conn: psycopg.Connection, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT *
        FROM sources
        WHERE is_active = true
          AND fetch_method = 'http_get'
        ORDER BY priority, source_name
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def record_fetch_result(
    conn: psycopg.Connection,
    run_id: str,
    source: dict[str, Any],
    result: FetchResult,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO source_fetch_events (
                run_id,
                source_id,
                status,
                http_status,
                content_hash,
                object_path,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                source["source_id"],
                result.status,
                result.http_status,
                result.content_hash,
                result.object_path,
                result.error_message,
            ),
        )

        cur.execute(
            """
            UPDATE sources
            SET current_hash = COALESCE(%s, current_hash),
                last_fetch_at = now(),
                last_status = %s,
                last_http_status = %s,
                last_error = %s,
                updated_at = now()
            WHERE source_id = %s
            """,
            (
                result.content_hash,
                result.status,
                result.http_status,
                result.error_message,
                source["source_id"],
            ),
        )


def complete_ingestion_run(
    conn: psycopg.Connection,
    run_id: str,
    fetched_count: int,
    changed_count: int,
    failed_count: int,
) -> None:
    status = "success" if failed_count == 0 else "failed"

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_runs
            SET completed_at = now(),
                status = %s,
                fetched_count = %s,
                changed_count = %s,
                failed_count = %s
            WHERE run_id = %s
            """,
            (status, fetched_count, changed_count, failed_count, run_id),
        )


def main() -> int:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        sources = load_active_sources(conn, args.limit)
        run_id = create_ingestion_run(conn, len(sources))
        conn.commit()

        fetched_count = 0
        changed_count = 0
        failed_count = 0

        with httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for source in sources:
                result = fetch_source(client, raw_dir, source)
                record_fetch_result(conn, run_id, source, result)
                conn.commit()

                if result.status in {"success", "unchanged"}:
                    fetched_count += 1
                if result.status == "success":
                    changed_count += 1
                if result.status == "failed":
                    failed_count += 1

                print(
                    f"{result.status.upper():9} "
                    f"{source['source_name']} "
                    f"http={result.http_status or '-'} "
                    f"hash={(result.content_hash or '-')[:12]}"
                )

        complete_ingestion_run(conn, run_id, fetched_count, changed_count, failed_count)
        conn.commit()

    print(
        f"Run {run_id}: fetched={fetched_count} "
        f"changed={changed_count} failed={failed_count}"
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
