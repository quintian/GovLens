#!/usr/bin/env python3
"""Create pgvector embeddings for document chunks."""

from __future__ import annotations

import argparse
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from embedding_utils import EMBEDDING_DIMENSION, EMBEDDING_MODEL, embed_text, vector_literal


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed GovLens document chunks into pgvector."
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
        help="Optional maximum number of chunks to embed.",
    )
    parser.add_argument(
        "--model",
        default=EMBEDDING_MODEL,
        help="Embedding model/version label stored with each vector.",
    )
    return parser.parse_args()


def load_pending_chunks(
    conn: psycopg.Connection,
    model: str,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            c.chunk_id,
            c.document_id,
            c.source_id,
            c.chunk_text,
            c.chunk_hash,
            d.title
        FROM document_chunks c
        JOIN documents d ON d.document_id = c.document_id
        LEFT JOIN chunk_embeddings e
            ON e.chunk_id = c.chunk_id
           AND e.embedding_model = %s
        WHERE e.embedding_id IS NULL
        ORDER BY d.title, c.chunk_index
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (model, limit)
    else:
        params = (model,)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def record_embedding(
    conn: psycopg.Connection,
    chunk: dict[str, Any],
    model: str,
) -> None:
    embedding = vector_literal(embed_text(chunk["chunk_text"]))

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chunk_embeddings (
                chunk_id,
                document_id,
                source_id,
                embedding_model,
                embedding_dimension,
                embedding,
                chunk_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            ON CONFLICT (chunk_id, embedding_model) DO UPDATE SET
                embedding_dimension = EXCLUDED.embedding_dimension,
                embedding = EXCLUDED.embedding,
                chunk_hash = EXCLUDED.chunk_hash,
                created_at = now()
            """,
            (
                chunk["chunk_id"],
                chunk["document_id"],
                chunk["source_id"],
                model,
                EMBEDDING_DIMENSION,
                embedding,
                chunk["chunk_hash"],
            ),
        )


def main() -> int:
    args = parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        chunks = load_pending_chunks(conn, args.model, args.limit)
        embedded_count = 0

        for chunk in chunks:
            record_embedding(conn, chunk, args.model)
            conn.commit()
            embedded_count += 1

            if embedded_count % 50 == 0:
                print(f"Embedded {embedded_count} chunks...")

    print(
        "Embedding complete: "
        f"model={args.model} dimension={EMBEDDING_DIMENSION} chunks={embedded_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
