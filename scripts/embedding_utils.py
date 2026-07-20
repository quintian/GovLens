"""Local embedding helpers for the GovLens demo pipeline.

This module intentionally avoids external model downloads or API keys. It
creates deterministic hashing vectors so the pgvector workflow can be built and
tested offline. In production, this is the part we would replace with OpenAI,
SentenceTransformers, or another embedding service.
"""

from __future__ import annotations

import hashlib
import math
import re


EMBEDDING_DIMENSION = 128
EMBEDDING_MODEL = "local_hashing_v1"
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9'-]*")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def tokenize(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text.lower())
    return [token for token in tokens if token not in STOPWORDS]


def add_feature(vector: list[float], feature: str, weight: float) -> None:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    index = value % len(vector)
    sign = -1.0 if value & 1 else 1.0
    vector[index] += sign * weight


def embed_text(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    tokens = tokenize(text)

    for token in tokens:
        add_feature(vector, token, 1.0)

    for left, right in zip(tokens, tokens[1:]):
        add_feature(vector, f"{left}_{right}", 1.5)

    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector

    return [round(value / length, 8) for value in vector]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"
