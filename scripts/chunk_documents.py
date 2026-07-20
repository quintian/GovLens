#!/usr/bin/env python3
"""Split AI-ready documents into retrieval-sized text chunks."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


@dataclass
class DocumentChunk:
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    character_count: int
    word_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create retrieval chunks for AI-ready GovLens documents."
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
        help="Optional maximum number of documents to chunk.",
    )
    parser.add_argument(
        "--chunk-words",
        type=int,
        default=220,
        help="Target number of words per chunk.",
    )
    parser.add_argument(
        "--overlap-words",
        type=int,
        default=40,
        help="Number of words repeated between neighboring chunks.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(
    text: str,
    chunk_words: int,
    overlap_words: int,
) -> list[DocumentChunk]:
    if chunk_words <= 0:
        raise ValueError("--chunk-words must be greater than zero")
    if overlap_words < 0:
        raise ValueError("--overlap-words cannot be negative")
    if overlap_words >= chunk_words:
        raise ValueError("--overlap-words must be smaller than --chunk-words")

    words = normalize_text(text).split()
    chunks: list[DocumentChunk] = []
    start = 0

    while start < len(words):
        end = min(start + chunk_words, len(words))
        chunk_body = " ".join(words[start:end])
        chunk_hash = hashlib.sha256(chunk_body.encode("utf-8")).hexdigest()
        chunks.append(
            DocumentChunk(
                chunk_index=len(chunks) + 1,
                chunk_text=chunk_body,
                chunk_hash=chunk_hash,
                character_count=len(chunk_body),
                word_count=len(chunk_body.split()),
            )
        )

        if end == len(words):
            break

        start = end - overlap_words

    return chunks


def load_pending_documents(
    conn: psycopg.Connection,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            d.document_id,
            d.source_id,
            d.title,
            d.word_count,
            t.extracted_text
        FROM documents d
        JOIN extracted_text t ON t.extracted_text_id = d.extracted_text_id
        LEFT JOIN document_chunks c ON c.document_id = d.document_id
        WHERE d.document_status = 'ai_ready'
          AND c.document_id IS NULL
          AND t.extracted_text IS NOT NULL
        ORDER BY d.created_at
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def record_chunks(
    conn: psycopg.Connection,
    document: dict[str, Any],
    chunks: list[DocumentChunk],
) -> None:
    with conn.cursor() as cur:
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO document_chunks (
                    document_id,
                    source_id,
                    chunk_index,
                    chunk_text,
                    chunk_hash,
                    character_count,
                    word_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                    chunk_text = EXCLUDED.chunk_text,
                    chunk_hash = EXCLUDED.chunk_hash,
                    character_count = EXCLUDED.character_count,
                    word_count = EXCLUDED.word_count,
                    created_at = now()
                """,
                (
                    document["document_id"],
                    document["source_id"],
                    chunk.chunk_index,
                    chunk.chunk_text,
                    chunk.chunk_hash,
                    chunk.character_count,
                    chunk.word_count,
                ),
            )


def main() -> int:
    args = parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        documents = load_pending_documents(conn, args.limit)
        document_count = 0
        chunk_count = 0

        for document in documents:
            chunks = chunk_text(
                document["extracted_text"],
                args.chunk_words,
                args.overlap_words,
            )
            record_chunks(conn, document, chunks)
            conn.commit()

            document_count += 1
            chunk_count += len(chunks)
            print(
                f"CHUNKED {document['title']} "
                f"document_words={document['word_count']} "
                f"chunks={len(chunks)}"
            )

    print(
        "Chunking complete: "
        f"documents={document_count} chunks={chunk_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
