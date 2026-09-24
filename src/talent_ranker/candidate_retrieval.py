from __future__ import annotations

from .ranking import reciprocal_rank_fusion
from .schemas import HiringPriorities


def retrieve_pool(repo, encoder, query: str, priorities: HiringPriorities, limit: int, rrf_k: int):
    """Union holistic and explicit requirement searches before the reranking cutoff."""
    requirements = dict.fromkeys(
        value.strip()
        for values in (
            priorities.must_have_skills,
            priorities.must_have_requirements,
        )
        for value in values
        if value.strip()
    )
    queries = [query, *requirements]
    vectors = encoder.encode(queries, query=True)
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}
    traces: list[dict] = []
    for index, (text, vector) in enumerate(zip(queries, vectors, strict=True)):
        dense, lexical, found = repo.retrieve(text, vector, limit)
        traces.append({"query_index": index, "dense_ids": dense, "lexical_ids": lexical})
        for candidate_id, score in reciprocal_rank_fusion(dense, lexical, rrf_k).items():
            scores[candidate_id] = max(scores.get(candidate_id, 0.0), score)
        for candidate_id, record in found.items():
            if candidate_id not in records:
                records[candidate_id] = record
            else:
                old = records[candidate_id]["chunks"]
                old.extend(chunk for chunk in record["chunks"] if chunk not in old)
    ordered = sorted(scores, key=lambda candidate_id: (-scores[candidate_id], candidate_id))
    return ordered, scores, records, traces
