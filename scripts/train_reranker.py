#!/usr/bin/env python3
"""Train a lightweight ML reranker for GovLens retrieval candidates."""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import psycopg
from psycopg.rows import dict_row
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline

from embedding_utils import EMBEDDING_MODEL, embed_text, vector_literal
from retrieve_chunks import retrieve


DEFAULT_DATABASE_URL = "postgresql://govlens:govlens@localhost:5434/govlens"
DEFAULT_MODEL_PATH = "models/relevance_reranker.joblib"
DEFAULT_METRICS_PATH = "data/ml/reranker_metrics.json"


@dataclass
class TrainingExample:
    question: str
    text: str
    label: int
    hybrid_score: float
    title: str
    agency: str
    chunk_index: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and evaluate a TF-IDF + LogisticRegression reranker."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=40,
        help="Number of retrieval candidates collected per question.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top K used for hit-rate and precision metrics.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.25,
        help="Fraction of evaluation questions held out for testing.",
    )
    parser.add_argument(
        "--validation-size",
        type=float,
        default=0.25,
        help="Fraction of evaluation questions used to tune the blend weight.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=99,
        help="Random seed for the grouped train/validation/test split.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Where to save the trained reranker artifact.",
    )
    parser.add_argument(
        "--metrics-path",
        default=DEFAULT_METRICS_PATH,
        help="Where to save training/evaluation metrics JSON.",
    )
    return parser.parse_args()


def load_questions(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                evaluation_question_id,
                question_text,
                expected_title_contains,
                expected_source_url,
                expected_agency
            FROM evaluation_questions
            WHERE is_active = true
            ORDER BY question_text
            """
        )
        return list(cur.fetchall())


def matches_expected(row: dict[str, Any], question: dict[str, Any]) -> bool:
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


def candidate_text(question: str, row: dict[str, Any]) -> str:
    return (
        f"query: {question}\n"
        f"title: {row['title']}\n"
        f"agency: {row['agency']}\n"
        f"topic: {row['topic']}\n"
        f"document_type: {row['document_type']}\n"
        f"chunk: {row['preview']}"
    )


def build_examples(
    conn: psycopg.Connection,
    questions: list[dict[str, Any]],
    candidate_limit: int,
) -> list[TrainingExample]:
    examples: list[TrainingExample] = []

    for question in questions:
        query = question["question_text"]
        rows = retrieve(
            conn,
            query,
            vector_literal(embed_text(query)),
            EMBEDDING_MODEL,
            "hybrid",
            candidate_limit,
            None,
            None,
            None,
        )

        for row in rows:
            label = 1 if matches_expected(row, question) else 0
            examples.append(
                TrainingExample(
                    question=query,
                    text=candidate_text(query, row),
                    label=label,
                    hybrid_score=float(row["hybrid_score"]),
                    title=row["title"],
                    agency=row["agency"],
                    chunk_index=int(row["chunk_index"]),
                )
            )

    return examples


def split_question_sets(
    questions: list[str],
    validation_size: float,
    test_size: float,
    random_state: int,
) -> tuple[set[str], set[str], set[str]]:
    shuffled = list(questions)
    random.Random(random_state).shuffle(shuffled)
    validation_count = max(1, round(len(shuffled) * validation_size))
    test_count = max(1, round(len(shuffled) * test_size))

    if validation_count + test_count >= len(shuffled):
        raise ValueError("validation-size plus test-size leaves no training questions")

    validation_questions = set(shuffled[:validation_count])
    test_questions = set(shuffled[validation_count : validation_count + test_count])
    train_questions = set(shuffled[validation_count + test_count :])
    return train_questions, validation_questions, test_questions


def require_binary_labels(split_name: str, examples: list[TrainingExample]) -> None:
    labels = {example.label for example in examples}
    if labels != {0, 1}:
        raise ValueError(f"{split_name} split must contain positive and negative examples.")


def first_relevant_rank(rows: list[dict[str, Any]]) -> int | None:
    for index, row in enumerate(rows, start=1):
        if row["label"] == 1:
            return index
    return None


def grouped_metrics(
    examples: list[TrainingExample],
    scores: list[float],
    top_k: int,
) -> dict[str, float]:
    by_question: dict[str, list[dict[str, Any]]] = {}

    for example, score in zip(examples, scores):
        by_question.setdefault(example.question, []).append(
            {
                "label": example.label,
                "score": score,
            }
        )

    hits = 0
    reciprocal_ranks: list[float] = []
    precision_values: list[float] = []

    for rows in by_question.values():
        ranked = sorted(rows, key=lambda row: row["score"], reverse=True)
        rank = first_relevant_rank(ranked[:top_k])
        if rank is None:
            reciprocal_ranks.append(0.0)
        else:
            hits += 1
            reciprocal_ranks.append(1 / rank)

        top_rows = ranked[:top_k]
        positives = sum(row["label"] for row in top_rows)
        precision_values.append(positives / len(top_rows) if top_rows else 0.0)

    question_count = len(by_question)
    return {
        "questions": float(question_count),
        f"hit_rate_at_{top_k}": hits / question_count if question_count else 0.0,
        "mrr": sum(reciprocal_ranks) / question_count if question_count else 0.0,
        f"precision_at_{top_k}": (
            sum(precision_values) / question_count if question_count else 0.0
        ),
    }


def train_model(
    train_examples: list[TrainingExample],
) -> GridSearchCV:
    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    stop_words="english",
                    max_features=8000,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    solver="liblinear",
                ),
            ),
        ]
    )
    param_grid = {
        "tfidf__ngram_range": [(1, 1), (1, 2)],
        "classifier__C": [0.3, 1.0, 3.0],
    }
    groups = [example.question for example in train_examples]
    unique_groups = sorted(set(groups))
    cv = GroupKFold(n_splits=min(3, len(unique_groups)))

    search = GridSearchCV(
        pipeline,
        param_grid=param_grid,
        scoring="average_precision",
        cv=cv,
        n_jobs=1,
    )
    search.fit(
        [example.text for example in train_examples],
        [example.label for example in train_examples],
        groups=groups,
    )
    return search


def positive_probability(model: Any, examples: list[TrainingExample]) -> list[float]:
    probabilities = model.predict_proba([example.text for example in examples])
    return [float(row[1]) for row in probabilities]


def blended_scores(
    examples: list[TrainingExample],
    probabilities: list[float],
    model_weight: float,
) -> list[float]:
    return [
        model_weight * probability + (1 - model_weight) * example.hybrid_score
        for example, probability in zip(examples, probabilities)
    ]


def select_model_weight(
    validation_examples: list[TrainingExample],
    validation_probabilities: list[float],
    top_k: int,
) -> tuple[float, dict[str, float]]:
    candidates = [weight / 10 for weight in range(0, 11)]
    best_weight = 0.0
    best_metrics: dict[str, float] | None = None

    for weight in candidates:
        metrics = grouped_metrics(
            validation_examples,
            blended_scores(validation_examples, validation_probabilities, weight),
            top_k,
        )

        if best_metrics is None:
            best_weight = weight
            best_metrics = metrics
            continue

        current_key = (
            metrics["mrr"],
            metrics[f"hit_rate_at_{top_k}"],
            metrics[f"precision_at_{top_k}"],
        )
        best_key = (
            best_metrics["mrr"],
            best_metrics[f"hit_rate_at_{top_k}"],
            best_metrics[f"precision_at_{top_k}"],
        )

        if current_key > best_key:
            best_weight = weight
            best_metrics = metrics

    return best_weight, best_metrics or {}


def main() -> int:
    args = parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        questions = load_questions(conn)
        examples = build_examples(conn, questions, args.candidate_limit)

    question_texts = sorted({example.question for example in examples})
    train_questions, validation_questions, test_questions = split_question_sets(
        question_texts,
        args.validation_size,
        args.test_size,
        args.random_state,
    )
    train_examples = [
        example for example in examples if example.question in train_questions
    ]
    validation_examples = [
        example for example in examples if example.question in validation_questions
    ]
    test_examples = [
        example for example in examples if example.question in test_questions
    ]

    require_binary_labels("Train", train_examples)
    require_binary_labels("Validation", validation_examples)
    require_binary_labels("Test", test_examples)

    search = train_model(train_examples)
    best_model = search.best_estimator_
    validation_probabilities = positive_probability(best_model, validation_examples)
    model_probabilities = positive_probability(best_model, test_examples)
    model_weight, validation_blend_metrics = select_model_weight(
        validation_examples,
        validation_probabilities,
        args.top_k,
    )
    reranker_scores = blended_scores(test_examples, model_probabilities, model_weight)

    baseline_metrics = grouped_metrics(
        test_examples,
        [example.hybrid_score for example in test_examples],
        args.top_k,
    )
    reranker_metrics = grouped_metrics(test_examples, reranker_scores, args.top_k)
    y_true = [example.label for example in test_examples]
    y_pred = [1 if probability >= 0.5 else 0 for probability in model_probabilities]

    metrics = {
        "model": "tfidf_logistic_regression_reranker",
        "baseline": "hybrid_retrieval_score",
        "embedding_model": EMBEDDING_MODEL,
        "candidate_limit": args.candidate_limit,
        "top_k": args.top_k,
        "question_count": len(question_texts),
        "train_questions": len(train_questions),
        "validation_questions": len(validation_questions),
        "test_questions": len(test_questions),
        "train_examples": len(train_examples),
        "validation_examples": len(validation_examples),
        "test_examples": len(test_examples),
        "positive_examples": sum(example.label for example in examples),
        "negative_examples": len(examples) - sum(example.label for example in examples),
        "best_params": search.best_params_,
        "selected_model_weight": model_weight,
        "cv_average_precision": float(search.best_score_),
        "test_average_precision": float(
            average_precision_score(y_true, model_probabilities)
        ),
        "test_precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "test_recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "baseline_grouped_metrics": baseline_metrics,
        "validation_blend_metrics": validation_blend_metrics,
        "reranker_grouped_metrics": reranker_metrics,
        "leakage_control": "train/validation/test split grouped by question_text",
    }

    model_path = Path(args.model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": best_model,
            "metadata": metrics,
            "selected_model_weight": model_weight,
        },
        model_path,
    )

    metrics_path = Path(args.metrics_path)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("ML reranker training complete")
    print(f"model_path={model_path}")
    print(f"metrics_path={metrics_path}")
    print(f"best_params={metrics['best_params']}")
    print(f"selected_model_weight={model_weight:.1f}")
    print(
        "baseline "
        f"hit@{args.top_k}={baseline_metrics[f'hit_rate_at_{args.top_k}']:.2f} "
        f"mrr={baseline_metrics['mrr']:.2f}"
    )
    print(
        "reranker "
        f"hit@{args.top_k}={reranker_metrics[f'hit_rate_at_{args.top_k}']:.2f} "
        f"mrr={reranker_metrics['mrr']:.2f}"
    )
    print(
        f"test_average_precision={metrics['test_average_precision']:.2f} "
        f"test_precision={metrics['test_precision']:.2f} "
        f"test_recall={metrics['test_recall']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
