"""Find short, cited resume passages for each approved hiring criterion."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import remove_experience_durations
from .schemas import HiringPriorities


@dataclass(frozen=True)
class Criterion:
    category: str
    text: str

    @property
    def key(self) -> str:
        return f"{self.category}:{self.text.casefold()}"

    @property
    def search_query(self) -> str:
        """Leave room for a resume passage in a hosted reranker request."""
        words, size = [], 0
        for word in self.text.split():
            next_size = size + len(word.encode("utf-8")) + (1 if words else 0)
            if next_size > 220:
                break
            words.append(word)
            size = next_size
        return " ".join(words) or self.text.encode("utf-8")[:220].decode("utf-8", "ignore")


def approved_criteria(priorities: HiringPriorities) -> list[Criterion]:
    groups = (
        ("must_have_skills", priorities.must_have_skills),
        ("must_have_requirements", priorities.must_have_requirements),
        ("preferred_skills", priorities.preferred_skills),
        ("preferred_requirements", priorities.preferred_requirements),
    )
    if not any(values for _, values in groups):
        groups += (("role_responsibilities", priorities.role_responsibilities),)
    seen: set[str] = set()
    criteria: list[Criterion] = []
    for category, values in groups:
        for value in values:
            cleaned = remove_experience_durations(value).strip()
            if cleaned and cleaned.casefold() not in seen:
                criteria.append(Criterion(category, cleaned))
                seen.add(cleaned.casefold())
    return criteria


def _vector(value: str | None) -> np.ndarray | None:
    if not value:
        return None
    vector = np.fromstring(value.strip("[]"), sep=",", dtype=np.float32)
    return vector if vector.size and np.isfinite(vector).all() else None


def _best_chunks(
    chunks: list[dict], query: np.ndarray, criterion: str, count: int = 3,
) -> list[dict]:
    if not chunks:
        return []
    query_norm = np.linalg.norm(query)
    scores = []
    for chunk in chunks:
        vector = _vector(chunk.get("embedding"))
        if vector is None or vector.size != query.size or not query_norm:
            similarity = 0.0
        else:
            norm = np.linalg.norm(vector)
            similarity = float(np.dot(query, vector) / (query_norm * norm)) if norm else 0.0
        scores.append((similarity, chunk))
    selected = [chunk for _, chunk in sorted(
        scores, key=lambda item: (-item[0], item[1]["ordinal"]),
    )[:count]]
    exact = next((chunk for chunk in chunks if criterion.casefold() in chunk["content"].casefold()), None)
    if exact is not None and exact not in selected:
        selected.append(exact)
    return selected


def match_criteria(
    criteria: list[Criterion], candidate_chunks: dict[str, list[dict]], encoder, reranker,
) -> dict[str, list[dict]]:
    """Use vector recall, then cross-encoder relevance on individual passages."""
    matches: dict[str, list[dict]] = {candidate_id: [] for candidate_id in candidate_chunks}
    if not criteria or not candidate_chunks:
        return matches
    vectors = encoder.encode([criterion.search_query for criterion in criteria], query=True)
    for criterion, vector in zip(criteria, vectors, strict=True):
        owners, chunks = [], []
        for candidate_id, candidate in candidate_chunks.items():
            for chunk in _best_chunks(candidate, np.asarray(vector), criterion.text):
                owners.append(candidate_id)
                chunks.append(chunk)
        passages = [chunk["content"] for chunk in chunks]
        if passages and hasattr(reranker, "score_passages_with_windows"):
            logits, excerpts = reranker.score_passages_with_windows(
                criterion.search_query, passages,
            )
        else:
            scorer = reranker.score_passages if hasattr(reranker, "score_passages") else reranker.score
            logits = scorer(criterion.search_query, passages) if passages else []
            excerpts = passages
        best: dict[str, list[tuple[float, dict]]] = {}
        for candidate_id, chunk, excerpt, logit in zip(
            owners, chunks, excerpts, logits, strict=True,
        ):
            best.setdefault(candidate_id, []).append((float(logit), {**chunk, "content": excerpt}))
        values = {cid: max(row[0] for row in rows) for cid, rows in best.items()}
        for candidate_id, rows in best.items():
            rows.sort(key=lambda row: (-row[0], row[1]["ordinal"]))
            relative = sum(value < values[candidate_id] for value in values.values())
            percentile = relative / (len(values) - 1) if len(values) > 1 else 0.5
            matches[candidate_id].append({
                "category": criterion.category,
                "requirement": criterion.text,
                "passages": [row[1] for row in rows],
                "semantic_percentile": round(percentile, 6),
            })
    return matches
