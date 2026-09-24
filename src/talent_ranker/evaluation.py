from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _recall(candidate_ids: set[str], positives: set[str]) -> float:
    return len(candidate_ids & positives) / len(positives)


def evaluate_run(
    labels: Mapping[str, bool],
    trace: Sequence[dict],
    shortlist: Sequence[str],
    ranked: Sequence[dict],
    k: int = 10,
) -> dict[str, float | int]:
    """Offline binary-label metrics; unlabelled candidates are not assumed qualified."""
    positives = {candidate_id for candidate_id, relevant in labels.items() if relevant}
    if not positives:
        raise ValueError("at least one positively labelled candidate is required")
    dense = {cid for query in trace for cid in query["dense_ids"]}
    lexical = {cid for query in trace for cid in query["lexical_ids"]}
    top = [row["candidate_id"] for row in ranked[:k]]
    if any(candidate_id not in labels for candidate_id in top):
        raise ValueError("every returned top-k candidate needs a relevance label")
    hits = [int(cid in positives) for cid in top]
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, len(positives))))
    requirements = [item for row in ranked[:k] for item in row.get("requirement_evidence", [])]
    supported = sum(
        item["status"] in {"experience_evidence", "listed", "mentioned", "reported_match"}
        for item in requirements
    )
    return {
        "positive_labels": len(positives),
        "dense_recall": _recall(dense, positives),
        "lexical_recall": _recall(lexical, positives),
        "union_recall": _recall(dense | lexical, positives),
        "shortlist_recall": _recall(set(shortlist), positives),
        "precision_at_k": sum(hits) / k,
        "ndcg_at_k": dcg / ideal,
        "evidence_coverage_at_k": supported / len(requirements) if requirements else 0.0,
    }
