#!/usr/bin/env python3
"""Create normalized document records and quality results from extracted text."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


@dataclass
class QualityResult:
    rule_name: str
    severity: str
    passed: bool
    message: str
    measured_value: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize extracted text into document records and quality checks."
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
        help="Optional maximum number of extracted text records to process.",
    )
    parser.add_argument(
        "--min-characters",
        type=int,
        default=1000,
        help="Minimum character count required for AI-ready documents.",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=150,
        help="Minimum word count required for AI-ready documents.",
    )
    return parser.parse_args()


def load_pending_extractions(
    conn: psycopg.Connection,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            t.extracted_text_id,
            t.source_id,
            t.event_id,
            t.extraction_status,
            t.character_count,
            t.word_count,
            s.source_name,
            s.source_url,
            s.source_type,
            s.agency,
            s.domain,
            s.topic,
            e.content_hash
        FROM extracted_text t
        JOIN sources s ON s.source_id = t.source_id
        JOIN source_fetch_events e ON e.event_id = t.event_id
        LEFT JOIN documents d
            ON d.source_id = t.source_id
           AND d.content_hash = e.content_hash
        WHERE t.extraction_status IN ('success', 'quarantined')
          AND e.content_hash IS NOT NULL
          AND d.document_id IS NULL
        ORDER BY t.extracted_at
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def quality_checks(
    record: dict[str, Any],
    min_characters: int,
    min_words: int,
) -> list[QualityResult]:
    checks = [
        QualityResult(
            "title_present",
            "error",
            bool(record["source_name"].strip()),
            "Document title/source name is present.",
            record["source_name"],
        ),
        QualityResult(
            "agency_present",
            "error",
            bool(record["agency"].strip()),
            "Agency metadata is present.",
            record["agency"],
        ),
        QualityResult(
            "source_url_present",
            "error",
            bool(record["source_url"].strip()),
            "Source URL is present.",
            record["source_url"],
        ),
        QualityResult(
            "content_hash_present",
            "error",
            bool(record["content_hash"]),
            "Content hash is present for version tracking.",
            str(record["content_hash"] or ""),
        ),
        QualityResult(
            "extraction_success",
            "error",
            record["extraction_status"] == "success",
            "Text extraction completed successfully.",
            record["extraction_status"],
        ),
        QualityResult(
            "minimum_character_count",
            "error",
            record["character_count"] >= min_characters,
            f"Extracted text has at least {min_characters} characters.",
            str(record["character_count"]),
        ),
        QualityResult(
            "minimum_word_count",
            "error",
            record["word_count"] >= min_words,
            f"Extracted text has at least {min_words} words.",
            str(record["word_count"]),
        ),
    ]

    return checks


def document_status(checks: list[QualityResult]) -> str:
    has_error = any(not check.passed and check.severity == "error" for check in checks)
    return "quarantined" if has_error else "ai_ready"


def next_version_number(conn: psycopg.Connection, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
            FROM documents
            WHERE source_id = %s
            """,
            (source_id,),
        )
        return int(cur.fetchone()["next_version"])


def upsert_document(
    conn: psycopg.Connection,
    record: dict[str, Any],
    status: str,
) -> str:
    version_number = next_version_number(conn, record["source_id"])

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (
                source_id,
                event_id,
                extracted_text_id,
                title,
                source_url,
                agency,
                domain,
                topic,
                document_type,
                content_hash,
                version_number,
                document_status,
                character_count,
                word_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, content_hash) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                extracted_text_id = EXCLUDED.extracted_text_id,
                title = EXCLUDED.title,
                source_url = EXCLUDED.source_url,
                agency = EXCLUDED.agency,
                domain = EXCLUDED.domain,
                topic = EXCLUDED.topic,
                document_type = EXCLUDED.document_type,
                document_status = EXCLUDED.document_status,
                character_count = EXCLUDED.character_count,
                word_count = EXCLUDED.word_count,
                updated_at = now()
            RETURNING document_id
            """,
            (
                record["source_id"],
                record["event_id"],
                record["extracted_text_id"],
                record["source_name"],
                record["source_url"],
                record["agency"],
                record["domain"],
                record["topic"],
                record["source_type"],
                record["content_hash"],
                version_number,
                status,
                record["character_count"],
                record["word_count"],
            ),
        )
        return str(cur.fetchone()["document_id"])


def record_quality_results(
    conn: psycopg.Connection,
    document_id: str,
    checks: list[QualityResult],
) -> None:
    with conn.cursor() as cur:
        for check in checks:
            cur.execute(
                """
                INSERT INTO quality_results (
                    document_id,
                    rule_name,
                    severity,
                    passed,
                    message,
                    measured_value
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, rule_name) DO UPDATE SET
                    severity = EXCLUDED.severity,
                    passed = EXCLUDED.passed,
                    message = EXCLUDED.message,
                    measured_value = EXCLUDED.measured_value,
                    created_at = now()
                """,
                (
                    document_id,
                    check.rule_name,
                    check.severity,
                    check.passed,
                    check.message,
                    check.measured_value,
                ),
            )


def main() -> int:
    args = parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        records = load_pending_extractions(conn, args.limit)

        ready_count = 0
        quarantined_count = 0

        for record in records:
            checks = quality_checks(record, args.min_characters, args.min_words)
            status = document_status(checks)
            document_id = upsert_document(conn, record, status)
            record_quality_results(conn, document_id, checks)
            conn.commit()

            if status == "ai_ready":
                ready_count += 1
            else:
                quarantined_count += 1

            failed_rules = [check.rule_name for check in checks if not check.passed]
            print(
                f"{status.upper():11} "
                f"{record['source_name']} "
                f"chars={record['character_count']} "
                f"words={record['word_count']} "
                f"failed_rules={','.join(failed_rules) or '-'}"
            )

    print(
        "Document build complete: "
        f"ai_ready={ready_count} quarantined={quarantined_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
