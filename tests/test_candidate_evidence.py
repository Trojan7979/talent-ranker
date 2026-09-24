from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from talent_ranker.api import app, get_candidate_evidence

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeRepository:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls: list[tuple[str, str]] = []

    def get_candidate_evidence(self, run_id: str, candidate_id: str):
        self.calls.append((run_id, candidate_id))
        return self.evidence


def test_get_candidate_evidence_returns_persisted_ranking_evidence():
    repository = FakeRepository(
        {
            "run_id": str(RUN_ID),
            "job_id": "senior-ai-engineer",
            "job_profile_version_id": "22222222-2222-2222-2222-222222222222",
            "candidate_id": "CAND_0001",
            "rank": 1,
            "score": 0.91,
            "score_components": {"semantic": 0.9},
            "evidence": ["Built production retrieval systems."],
            "reasoning": "Strong match.",
            "created_at": datetime(2026, 9, 22, tzinfo=UTC),
        }
    )
    app.state.pipeline = SimpleNamespace(repo=repository)

    response = get_candidate_evidence(RUN_ID, "CAND_0001")

    assert response.rank == 1
    assert str(response.job_profile_version_id) == "22222222-2222-2222-2222-222222222222"
    assert response.evidence == ["Built production retrieval systems."]
    assert repository.calls == [(str(RUN_ID), "CAND_0001")]


def test_get_candidate_evidence_returns_404_when_result_is_absent():
    app.state.pipeline = SimpleNamespace(repo=FakeRepository(None))

    with pytest.raises(HTTPException) as error:
        get_candidate_evidence(RUN_ID, "CAND_0001")

    assert error.value.status_code == 404
