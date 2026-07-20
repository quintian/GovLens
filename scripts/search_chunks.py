#!/usr/bin/env python3
"""Search embedded GovLens chunks with pgvector cosine distance."""

from __future__ import annotations

import argparse
import os

import psycopg
from psycopg.rows import dict_row

from embedding_utils import EMBEDDING_MODEL, embed_text, vector_literal


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search GovLens chunks by vector similarity."
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
        help="Number of matching chunks to return.",
    )
    parser.add_argument(
        "--model",
        default=EMBEDDING_MODEL,
        help="Embedding model/version label to search.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query_vector = vector_literal(embed_text(args.query))

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.title,
                    d.agency,
                    d.source_url,
                    c.chunk_index,
                    c.word_count,
                    1 - (e.embedding <=> %s::vector) AS similarity,
                    left(c.chunk_text, 360) AS preview
                FROM chunk_embeddings e
                JOIN document_chunks c ON c.chunk_id = e.chunk_id
                JOIN documents d ON d.document_id = e.document_id
                WHERE e.embedding_model = %s
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vector, args.model, query_vector, args.limit),
            )
            rows = cur.fetchall()

    for index, row in enumerate(rows, start=1):
        print(
            f"{index}. {row['title']} "
            f"chunk={row['chunk_index']} "
            f"similarity={row['similarity']:.4f}"
        )
        print(f"   agency={row['agency']}")
        print(f"   url={row['source_url']}")
        print(f"   preview={row['preview'].strip()}...")

    if not rows:
        print("No embedded chunks found. Run scripts/embed_chunks.py first.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
