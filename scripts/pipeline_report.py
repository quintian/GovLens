#!/usr/bin/env python3
"""Print a compact GovLens pipeline status report."""

from __future__ import annotations

import argparse
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show GovLens ingestion, retrieval, and evaluation status."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    return parser.parse_args()


def fetch_all(conn: psycopg.Connection, sql: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def print_rows(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{title}")
    print("-" * len(title))

    if not rows:
        print("No rows found.")
        return

    headers = list(rows[0].keys())
    widths = {
        header: max(
            len(header),
            max(len(str(row[header] if row[header] is not None else "")) for row in rows),
        )
        for header in headers
    }

    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))

    for row in rows:
        print(
            " | ".join(
                str(row[header] if row[header] is not None else "").ljust(widths[header])
                for header in headers
            )
        )


def main() -> int:
    args = parse_args()

    queries = {
        "Source Status": """
            SELECT
                last_status,
                count(*) AS sources
            FROM sources
            GROUP BY last_status
            ORDER BY last_status
        """,
        "Document Readiness": """
            SELECT
                document_status,
                count(*) AS documents,
                sum(word_count) AS total_words
            FROM documents
            GROUP BY document_status
            ORDER BY document_status
        """,
        "Chunk And Embedding Coverage": """
            SELECT
                count(DISTINCT c.document_id) AS chunked_documents,
                count(c.chunk_id) AS chunks,
                count(e.embedding_id) AS embeddings
            FROM document_chunks c
            LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
        """,
        "Latest Retrieval Queries": """
            SELECT
                query_text,
                retrieval_mode,
                result_count,
                latency_ms
            FROM retrieval_queries
            ORDER BY started_at DESC
            LIMIT 5
        """,
        "Latest Evaluation Runs": """
            SELECT
                retrieval_mode,
                top_k,
                question_count,
                hit_count,
                round(mean_reciprocal_rank::numeric, 3) AS mrr
            FROM evaluation_runs
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 5
        """,
    }

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        for title, sql in queries.items():
            print_rows(title, fetch_all(conn, sql))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
