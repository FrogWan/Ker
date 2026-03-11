from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass


@dataclass
class MemoryHit:
    path: str
    score: float
    snippet: str
    source: str = ""


# ~50 common English stop words
STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "was", "are",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "not", "no", "so", "if",
    "as", "just", "about", "into", "than", "then", "its", "my", "your",
    "we", "they", "he", "she", "i", "me", "you",
}

# Default source weights for composite scoring
DEFAULT_SOURCE_WEIGHTS: dict[str, float] = {
    "working": 1.5,
    "daily": 1.2,
    "episodes": 1.0,
    "chat_history": 0.8,
    "MEMORY.md": 1.0,
    "HISTORY.md": 0.9,
    "ERROR_LOG": 0.7,
}


class MemoryScorer:
    """Unified TF-IDF + composite scoring for all memory tiers."""

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Split text into tokens: handles CamelCase, strips stop words, naive suffix stemming."""
        # Split CamelCase: "CamelCase" -> "Camel Case"
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        # Extract word tokens
        raw = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        tokens: list[str] = []
        for t in raw:
            if t in STOP_WORDS:
                continue
            # Naive suffix stemming: strip common suffixes
            stemmed = t
            for suffix in ("ing", "tion", "sion", "ment", "ness", "able", "ible", "ous", "ive", "ed", "ly", "er", "es", "s"):
                if len(stemmed) > len(suffix) + 2 and stemmed.endswith(suffix):
                    stemmed = stemmed[: -len(suffix)]
                    break
            tokens.append(stemmed)
        return tokens

    @staticmethod
    def score(
        chunks: list[dict],
        query: str,
        top_k: int = 5,
        source_weights: dict[str, float] | None = None,
    ) -> list[MemoryHit]:
        """Score chunks against query using TF-IDF cosine + recency + importance + source weight.

        Each chunk dict should have: text, ts, path, and optionally importance and source.
        final_score = tfidf_cosine * exp(-0.02 * age_days) * importance * source_weight
        """
        if not chunks or not query.strip():
            return []

        weights = source_weights or DEFAULT_SOURCE_WEIGHTS
        tokenize = MemoryScorer.tokenize

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        chunk_tokens = [tokenize(c.get("text", "")) for c in chunks]
        n = len(chunk_tokens)

        # Document frequency
        df: dict[str, int] = {}
        for toks in chunk_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

        def tfidf(tokens: list[str]) -> dict[str, float]:
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            out: dict[str, float] = {}
            for t, c in tf.items():
                out[t] = c * (math.log((n + 1) / (df.get(t, 0) + 1)) + 1)
            return out

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            common = set(a).intersection(b)
            if not common:
                return 0.0
            dot = sum(a[k] * b[k] for k in common)
            na = math.sqrt(sum(v * v for v in a.values()))
            nb = math.sqrt(sum(v * v for v in b.values()))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        qvec = tfidf(query_tokens)
        scored: list[MemoryHit] = []
        now = time.time()

        for i, toks in enumerate(chunk_tokens):
            base = cosine(qvec, tfidf(toks))
            if base <= 0:
                continue

            chunk = chunks[i]
            age_days = max(0.0, (now - float(chunk.get("ts", 0))) / 86400.0)
            importance = float(chunk.get("importance", 0.5))
            source = chunk.get("source", "")
            source_weight = weights.get(source, 1.0)

            final = base * math.exp(-0.02 * age_days) * importance * source_weight

            scored.append(MemoryHit(
                path=chunk.get("path", ""),
                score=final,
                snippet=chunk.get("text", "")[:500],
                source=source,
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
