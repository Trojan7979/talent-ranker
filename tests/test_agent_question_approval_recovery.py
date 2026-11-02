from types import SimpleNamespace
from uuid import uuid4

import pytest

from sieve_app import agent_api


def test_question_approval_retries_after_campaign_proposal_failure(monkeypatch):
    session_id, config_id, campaign_id, run_id = (uuid4() for _ in range(4))
    row = {"job_id": "role-1", "ranking_run_id": run_id, "campaign_id": None}
    attempts = []
    created = []
    messages = []

    class Store:
        def get_session(self, *_):
            return row

        def approve_questions(self, *_):
            return config_id, 4

        def campaign_for_question_config(self, *_):
            return {"id": campaign_id} if created else None

        def set_campaign(self, _, value):
            row["campaign_id"] = value

        def add_message(self, _, role, content):
            messages.append((role, content))

    class Pipeline:
        def __init__(self, *_):
            pass

        def propose(self, _):
            attempts.append("called")
            if len(attempts) == 1:
                raise ValueError("temporary ranking failure")
            created.append(campaign_id)
            return {"id": campaign_id}

    settings = SimpleNamespace(
        workspace_id="test", max_recipients=10, allowed_job_ids=lambda actor: {"role-1"}
    )
    store = Store()
    monkeypatch.setattr(agent_api, "services", lambda request: (settings, None, None, store))
    monkeypatch.setattr(agent_api, "ScreeningPipeline", Pipeline)
    monkeypatch.setattr(agent_api, "view", lambda store, row, settings: row.copy())
    identity = SimpleNamespace(jobs=lambda actor, workspace: frozenset({"role-1"}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        screening_settings=settings, recruiter_identity=identity)))
    details = agent_api.ApproveAgentQuestions(expected_revision=2)

    with pytest.raises(agent_api.HTTPException) as failure:
        agent_api.approve_questions(session_id, details, "recruiter", request)
    assert failure.value.status_code == 409
    assert row["campaign_id"] is None

    result = agent_api.approve_questions(session_id, details, "recruiter", request)
    assert result["campaign_id"] == campaign_id
    assert len(messages) == 1

    agent_api.approve_questions(session_id, details, "recruiter", request)
    assert len(attempts) == 2
    assert len(messages) == 1
