#!/usr/bin/env python3
"""Evaluate GovLens retrieval against expected source/document matches."""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

from embedding_utils import EMBEDDING_MODEL, embed_text, vector_literal
from retrieve_chunks import filter_value, retrieve


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run retrieval evaluation questions and store metrics."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of retrieved chunks checked for each question.",
    )
    parser.add_argument(
        "--mode",
        choices=["hybrid", "keyword", "vector"],
        default="hybrid",
        help="Retrieval mode to evaluate.",
    )
    parser.add_argument(
        "--model",
        default=EMBEDDING_MODEL,
        help="Embedding model/version label to evaluate.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of active evaluation questions.",
    )
    return parser.parse_args()


def load_questions(
    conn: psycopg.Connection,
    limit: int | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            evaluation_question_id,
            question_text,
            expected_title_contains,
            expected_source_url,
            expected_agency
        FROM evaluation_questions
        WHERE is_active = true
        ORDER BY created_at, question_text
    """

    if limit:
        sql += " LIMIT %s"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def create_evaluation_run(
    conn: psycopg.Connection,
    mode: str,
    model: str,
    top_k: int,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluation_runs (
                retrieval_mode,
                embedding_model,
                top_k
            )
            VALUES (%s, %s, %s)
            RETURNING evaluation_run_id
            """,
            (mode, model, top_k),
        )
        return str(cur.fetchone()["evaluation_run_id"])


def row_matches_expectation(
    row: dict[str, Any],
    question: dict[str, Any],
) -> bool:
    title_expected = question["expected_title_contains"]
    source_expected = question["expected_source_url"]
    agency_expected = question["expected_agency"]

    if title_expected and title_expected.lower() not in row["title"].lower():
        return False
    if source_expected and source_expected != row["source_url"]:
        return False
    if agency_expected and agency_expected.lower() not in row["agency"].lower():
        return False
    return True


def first_relevant_rank(
    rows: list[dict[str, Any]],
    question: dict[str, Any],
) -> int | None:
    for rank, row in enumerate(rows, start=1):
        if row_matches_expectation(row, question):
            return rank
    return None


def record_evaluation_result(
    conn: psycopg.Connection,
    run_id: str,
    question: dict[str, Any],
    rows: list[dict[str, Any]],
    rank: int | None,
) -> None:
    top = rows[0] if rows else {}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluation_results (
                evaluation_run_id,
                evaluation_question_id,
                matched,
                first_relevant_rank,
                top_title,
                top_source_url,
                top_hybrid_score
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                question["evaluation_question_id"],
                rank is not None,
                rank,
                top.get("title"),
                top.get("source_url"),
                top.get("hybrid_score"),
            ),
        )


def complete_evaluation_run(
    conn: psycopg.Connection,
    run_id: str,
    question_count: int,
    hit_count: int,
    mean_reciprocal_rank: float,
    latency_ms: int,
) -> None:
    notes = f"latency_ms={latency_ms}"

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluation_runs
            SET completed_at = now(),
                question_count = %s,
                hit_count = %s,
                mean_reciprocal_rank = %s,
                notes = %s
            WHERE evaluation_run_id = %s
            """,
            (question_count, hit_count, mean_reciprocal_rank, notes, run_id),
        )


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        questions = load_questions(conn, args.limit)
        run_id = create_evaluation_run(conn, args.mode, args.model, args.top_k)
        conn.commit()

        hit_count = 0
        reciprocal_ranks: list[float] = []

        for question in questions:
            query_vector = vector_literal(embed_text(question["question_text"]))
            rows = retrieve(
                conn,
                question["question_text"],
                query_vector,
                args.model,
                args.mode,
                args.top_k,
                filter_value(question["expected_agency"]),
                None,
                None,
            )
            rank = first_relevant_rank(rows, question)
            record_evaluation_result(conn, run_id, question, rows, rank)
            conn.commit()

            if rank is not None:
                hit_count += 1
                reciprocal_ranks.append(1 / rank)
                outcome = f"HIT@{rank}"
            else:
                reciprocal_ranks.append(0.0)
                outcome = "MISS"

            top_title = rows[0]["title"] if rows else "-"
            print(
                f"{outcome:6} {question['question_text']} "
                f"top={top_title}"
            )

        question_count = len(questions)
        mean_reciprocal_rank = (
            sum(reciprocal_ranks) / question_count if question_count else 0.0
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        complete_evaluation_run(
            conn,
            run_id,
            question_count,
            hit_count,
            mean_reciprocal_rank,
            latency_ms,
        )
        conn.commit()

    hit_rate = hit_count / question_count if question_count else 0.0
    print(
        f"Evaluation {run_id}: "
        f"questions={question_count} "
        f"hit_rate={hit_rate:.2f} "
        f"mrr={mean_reciprocal_rank:.2f}"
    )
    return 0 if hit_count == question_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
