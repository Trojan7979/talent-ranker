from __future__ import annotations

from .access import RecruiterScope
from .calibration import remove_experience_durations
from .ranking import reciprocal_rank_fusion
from .schemas import HiringPriorities


def retrieve_pool(
    repo, encoder, query: str, priorities: HiringPriorities, limit: int, rrf_k: int,
    scope: RecruiterScope,
):
    """Union holistic and explicit requirement searches before the reranking cutoff."""
    qualification_groups = (
        priorities.must_have_skills, priorities.must_have_requirements,
        priorities.preferred_skills, priorities.preferred_requirements,
    )
    groups = qualification_groups if any(qualification_groups) else (priorities.role_responsibilities,)
    requirements = dict.fromkeys(
        remove_experience_durations(value)
        for values in groups
        for value in values
        if remove_experience_durations(value)
    )
    queries = list(dict.fromkeys([query, *requirements]))
    vectors = encoder.encode(queries, query=True)
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}
    traces: list[dict] = []
    for index, (text, vector) in enumerate(zip(queries, vectors, strict=True)):
        dense, lexical, found = repo.retrieve(text, vector, limit, scope)
        traces.append({"query_index": index, "dense_ids": dense, "lexical_ids": lexical})
        for candidate_id, score in reciprocal_rank_fusion(dense, lexical, rrf_k).items():
            scores[candidate_id] = scores.get(candidate_id, 0.0) + score
        for candidate_id, record in found.items():
            if candidate_id not in records:
                records[candidate_id] = record
            else:
                old = records[candidate_id]["chunks"]
                old.extend(chunk for chunk in record["chunks"] if chunk not in old)
    ordered = sorted(scores, key=lambda candidate_id: (-scores[candidate_id], candidate_id))
    return ordered, scores, records, traces
