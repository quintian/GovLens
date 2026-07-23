#!/usr/bin/env python3
"""Retrieve GovLens candidates and rerank them with the saved ML model."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import joblib
import psycopg
from psycopg.rows import dict_row

from embedding_utils import EMBEDDING_MODEL, embed_text, vector_literal
from retrieve_chunks import retrieve
from train_reranker import DEFAULT_MODEL_PATH, candidate_text


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rerank GovLens retrieval candidates with the trained ML model."
    )
    parser.add_argument("query", help="Question or search text.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=20,
        help="Number of hybrid retrieval candidates to rerank.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of reranked results to print.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Path to the trained reranker artifact.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_path = Path(args.model_path)
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model artifact not found: {model_path}. Run scripts/train_reranker.py first."
        )

    artifact = joblib.load(model_path)
    model = artifact["model"]
    model_weight = artifact.get("selected_model_weight", 0.0)

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        rows = retrieve(
            conn,
            args.query,
            vector_literal(embed_text(args.query)),
            EMBEDDING_MODEL,
            "hybrid",
            args.candidate_limit,
            None,
            None,
            None,
        )

    texts = [candidate_text(args.query, row) for row in rows]
    probabilities = model.predict_proba(texts)
    scored_rows = []

    for row, probability in zip(rows, probabilities):
        relevance_probability = float(probability[1])
        ml_score = (
            model_weight * relevance_probability
            + (1 - model_weight) * float(row["hybrid_score"])
        )
        scored_rows.append(
            {
                **row,
                "relevance_probability": relevance_probability,
                "ml_score": ml_score,
            }
        )

    ranked_rows = sorted(
        scored_rows,
        key=lambda row: row["ml_score"],
        reverse=True,
    )

    print(f"model_weight={model_weight:.1f}")
    for rank, row in enumerate(ranked_rows[: args.limit], start=1):
        print(
            f"{rank}. {row['title']} "
            f"chunk={row['chunk_index']} "
            f"ml_score={row['ml_score']:.4f} "
            f"model_probability={row['relevance_probability']:.4f} "
            f"hybrid={row['hybrid_score']:.4f}"
        )
        print(f"   agency={row['agency']}")
        print(f"   citation={row['source_url']}")
        print(f"   preview={row['preview'].strip()}...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
