"""Repeat rankings are explicit and keep screening tied to its original run."""

from uuid import uuid4
from contextlib import nullcontext

import pytest

from sieve_app.agent_reranking import AgentRerankingWorkflow
from sieve_app.agent_reranking_store import AgentRerankingStoreMixin


def test_explicit_top_n_request_queues_fresh_ranking_in_same_conversation():
    queued = []
    workflow = AgentRerankingWorkflow(type("Store", (), {
        "queue_reranking": lambda self, session, top_k: (queued.append((session, top_k)) or 2),
    })())
    session = {"id": uuid4(), "ranking_run_id": uuid4(), "setup_stage": "ranked"}

    assert workflow.is_request("Rank top 12 candidates using current indexed resumes")
    assert not workflow.is_request("Show the top 12 candidates from this run")
    reply = workflow.handle(session, "Rank top 12 candidates using current indexed resumes")

    assert queued == [(session, 12)]
    assert "criteria version 2" in reply
    assert "earlier saved run remains available" in reply


def test_reranking_does_not_reuse_old_screening_draft():
    workflow = AgentRerankingWorkflow(type("Store", (), {
        "queue_reranking": lambda *args: pytest.fail("screening must remain tied to original run"),
    })())
    session = {"question_draft": {"must_haves": []}}

    assert "Start a new conversation" in workflow.handle(session, "Rank top 12 candidates")


def test_reranking_rejects_invalid_top_n():
    workflow = AgentRerankingWorkflow(None)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        workflow.handle({}, "Rank top 1001 candidates")


def test_reranking_store_accepts_dictionary_database_rows():
    class Cursor:
        def __init__(self):
            self.rows = [{"profile_version_id": uuid4(), "version": 2},
                         {"id": uuid4()}, {"session_id": uuid4()}]

        def execute(self, query, values):
            assert values

        def fetchone(self):
            return self.rows.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Connection:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

        def transaction(self):
            return nullcontext()

    conn = Connection()
    store = AgentRerankingStoreMixin()
    store.repository = type("Repo", (), {"connection": lambda self: nullcontext(conn)})()
    session = {"id": uuid4(), "ranking_run_id": uuid4(), "job_id": "role",
               "workspace_id": "workspace", "actor_id": str(uuid4())}

    assert store.queue_reranking(session, 12) == 2
