#!/usr/bin/env python3
"""Extract readable text from raw GovLens source files."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from bs4 import BeautifulSoup
from psycopg.rows import dict_row
from pypdf import PdfReader


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


@dataclass
class ExtractionResult:
    status: str
    method: str
    text: str | None = None
    error_message: str | None = None

    @property
    def character_count(self) -> int:
        return len(self.text or "")

    @property
    def word_count(self) -> int:
        return len((self.text or "").split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text from successful GovLens raw fetch events."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of raw objects to extract.",
    )
    parser.add_argument(
        "--min-characters",
        type=int,
        default=500,
        help="Minimum character count for a successful extraction.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return re.sub(r"[ \t]+", " ", cleaned)


def extract_html(path: Path) -> ExtractionResult:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    text = normalize_text(soup.get_text("\n"))
    return ExtractionResult(status="success", method="html_text", text=text)


def extract_pdf(path: Path) -> ExtractionResult:
    reader = PdfReader(str(path))
    page_text = []

    for page in reader.pages:
        page_text.append(page.extract_text() or "")

    text = normalize_text("\n".join(page_text))
    return ExtractionResult(status="success", method="pdf_text", text=text)


def extract_file(source_type: str, object_path: str, min_characters: int) -> ExtractionResult:
    path = Path(object_path)

    try:
        if source_type == "html":
            result = extract_html(path)
        elif source_type == "pdf":
            result = extract_pdf(path)
        else:
            return ExtractionResult(
                status="failed",
                method="unsupported",
                error_message=f"Unsupported source_type for extraction: {source_type}",
            )

        if result.character_count < min_characters:
            return ExtractionResult(
                status="quarantined",
                method=result.method,
                text=result.text,
                error_message=(
                    f"Extracted text too short: {result.character_count} "
                    f"characters, minimum is {min_characters}"
                ),
            )

        return result
    except Exception as error:
        return ExtractionResult(
            status="failed",
            method=f"{source_type}_text",
            error_message=str(error),
        )


def load_pending_fetch_events(
    conn: psycopg.Connection,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            e.event_id,
            e.source_id,
            e.object_path,
            s.source_name,
            s.source_type
        FROM source_fetch_events e
        JOIN sources s ON s.source_id = e.source_id
        LEFT JOIN extracted_text t ON t.event_id = e.event_id
        WHERE e.status = 'success'
          AND e.object_path IS NOT NULL
          AND t.event_id IS NULL
        ORDER BY e.fetched_at
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def record_extraction(
    conn: psycopg.Connection,
    event: dict[str, Any],
    result: ExtractionResult,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extracted_text (
                source_id,
                event_id,
                object_path,
                extraction_method,
                extraction_status,
                extracted_text,
                character_count,
                word_count,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO UPDATE SET
                extraction_method = EXCLUDED.extraction_method,
                extraction_status = EXCLUDED.extraction_status,
                extracted_text = EXCLUDED.extracted_text,
                character_count = EXCLUDED.character_count,
                word_count = EXCLUDED.word_count,
                error_message = EXCLUDED.error_message,
                extracted_at = now()
            """,
            (
                event["source_id"],
                event["event_id"],
                event["object_path"],
                result.method,
                result.status,
                result.text,
                result.character_count,
                result.word_count,
                result.error_message,
            ),
        )


def main() -> int:
    args = parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        events = load_pending_fetch_events(conn, args.limit)

        success_count = 0
        failed_count = 0
        quarantined_count = 0

        for event in events:
            result = extract_file(
                event["source_type"],
                event["object_path"],
                args.min_characters,
            )
            record_extraction(conn, event, result)
            conn.commit()

            if result.status == "success":
                success_count += 1
            elif result.status == "quarantined":
                quarantined_count += 1
            else:
                failed_count += 1

            print(
                f"{result.status.upper():11} "
                f"{event['source_name']} "
                f"method={result.method} "
                f"chars={result.character_count} "
                f"words={result.word_count}"
            )

    print(
        "Extraction complete: "
        f"success={success_count} "
        f"quarantined={quarantined_count} "
        f"failed={failed_count}"
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
