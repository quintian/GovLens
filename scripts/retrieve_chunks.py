#!/usr/bin/env python3
"""Run citation-ready hybrid retrieval over GovLens chunks."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

from embedding_utils import EMBEDDING_MODEL, embed_text, vector_literal


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"
VALID_MODES = {"vector", "keyword", "hybrid"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrieve GovLens chunks with vector, keyword, or hybrid ranking."
    )
    parser.add_argument("query", help="Question or search text.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of ranked chunks to return.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_MODES),
        default="hybrid",
        help="Retrieval mode.",
    )
    parser.add_argument(
        "--model",
        default=EMBEDDING_MODEL,
        help="Embedding model/version label to search.",
    )
    parser.add_argument("--agency", help="Optional agency filter.")
    parser.add_argument("--topic", help="Optional topic filter.")
    parser.add_argument("--document-type", help="Optional document type filter.")
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Return results without writing retrieval query/result logs.",
    )
    return parser.parse_args()


def filter_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return f"%{value}%" if value else None


def order_clause(mode: str) -> str:
    if mode == "vector":
        return "vector_similarity DESC"
    if mode == "keyword":
        return "keyword_score DESC, vector_similarity DESC"
    return "hybrid_score DESC, vector_similarity DESC"


def keyword_filter(mode: str) -> str:
    if mode == "keyword":
        return "WHERE keyword_score > 0"
    return ""


def retrieve(
    conn: psycopg.Connection,
    query: str,
    query_vector: str,
    model: str,
    mode: str,
    limit: int,
    agency: str | None,
    topic: str | None,
    document_type: str | None,
) -> list[dict[str, Any]]:
    sql = f"""
        WITH scored AS (
            SELECT
                c.chunk_id,
                c.document_id,
                c.source_id,
                c.chunk_index,
                c.word_count,
                c.chunk_text,
                d.title,
                d.agency,
                d.topic,
                d.document_type,
                d.source_url,
                d.version_number,
                1 - (e.embedding <=> %s::vector) AS vector_similarity,
                ts_rank_cd(
                    to_tsvector('english', c.chunk_text),
                    websearch_to_tsquery('english', %s)
                ) AS keyword_score
            FROM chunk_embeddings e
            JOIN document_chunks c ON c.chunk_id = e.chunk_id
            JOIN documents d ON d.document_id = e.document_id
            WHERE e.embedding_model = %s
              AND (%s::text IS NULL OR d.agency ILIKE %s)
              AND (%s::text IS NULL OR d.topic ILIKE %s)
              AND (%s::text IS NULL OR d.document_type ILIKE %s)
        ),
        ranked AS (
            SELECT
                *,
                (
                    0.65 * vector_similarity
                    + 0.35 * LEAST(keyword_score * 8, 1.0)
                ) AS hybrid_score
            FROM scored
        )
        SELECT
            chunk_id,
            document_id,
            source_id,
            chunk_index,
            word_count,
            title,
            agency,
            topic,
            document_type,
            source_url,
            version_number,
            vector_similarity,
            keyword_score,
            hybrid_score,
            left(chunk_text, 520) AS preview
        FROM ranked
        {keyword_filter(mode)}
        ORDER BY {order_clause(mode)}
        LIMIT %s
    """

    params = (
        query_vector,
        query,
        model,
        agency,
        agency,
        topic,
        topic,
        document_type,
        document_type,
        limit,
    )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def create_query_log(
    conn: psycopg.Connection,
    query: str,
    mode: str,
    model: str,
    filters: dict[str, str | None],
    result_count: int,
    latency_ms: int,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO retrieval_queries (
                query_text,
                retrieval_mode,
                embedding_model,
                filters,
                result_count,
                latency_ms
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s)
            RETURNING query_id
            """,
            (
                query,
                mode,
                model,
                json.dumps(filters),
                result_count,
                latency_ms,
            ),
        )
        return str(cur.fetchone()["query_id"])


def record_results(
    conn: psycopg.Connection,
    query_id: str,
    rows: list[dict[str, Any]],
) -> None:
    with conn.cursor() as cur:
        for rank, row in enumerate(rows, start=1):
            cur.execute(
                """
                INSERT INTO retrieval_results (
                    query_id,
                    chunk_id,
                    document_id,
                    source_id,
                    rank,
                    vector_similarity,
                    keyword_score,
                    hybrid_score
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    query_id,
                    row["chunk_id"],
                    row["document_id"],
                    row["source_id"],
                    rank,
                    row["vector_similarity"],
                    row["keyword_score"],
                    row["hybrid_score"],
                ),
            )


def print_results(rows: list[dict[str, Any]], query_id: str | None) -> None:
    if query_id:
        print(f"query_id={query_id}")

    if not rows:
        print("No matching chunks found.")
        return

    for rank, row in enumerate(rows, start=1):
        print(
            f"{rank}. {row['title']} "
            f"chunk={row['chunk_index']} "
            f"hybrid={row['hybrid_score']:.4f} "
            f"vector={row['vector_similarity']:.4f} "
            f"keyword={row['keyword_score']:.4f}"
        )
        print(
            f"   agency={row['agency']} "
            f"topic={row['topic']} "
            f"type={row['document_type']} "
            f"version={row['version_number']}"
        )
        print(f"   citation={row['source_url']}")
        print(f"   preview={row['preview'].strip()}...")


def main() -> int:
    args = parse_args()
    start = time.perf_counter()
    query_vector = vector_literal(embed_text(args.query))
    agency = filter_value(args.agency)
    topic = filter_value(args.topic)
    document_type = filter_value(args.document_type)

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        rows = retrieve(
            conn,
            args.query,
            query_vector,
            args.model,
            args.mode,
            args.limit,
            agency,
            topic,
            document_type,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        query_id = None
        if not args.no_log:
            filters = {
                "agency": args.agency,
                "topic": args.topic,
                "document_type": args.document_type,
            }
            query_id = create_query_log(
                conn,
                args.query,
                args.mode,
                args.model,
                filters,
                len(rows),
                latency_ms,
            )
            record_results(conn, query_id, rows)
            conn.commit()

    print_results(rows, query_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
