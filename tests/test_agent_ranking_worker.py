from types import SimpleNamespace
from uuid import uuid4

from sieve_app.agent_ranking_worker import AgentRankingWorker


def test_approved_ranking_job_publishes_saved_run():
    profile_id, session_id, run_id = (uuid4() for _ in range(3))
    job = {"session_id": session_id, "profile_version_id": profile_id, "top_k": 5, "attempts": 1}
    calls = []
    store = SimpleNamespace(
        claim_ranking=lambda: job,
        ranking_session=lambda _: {
            "workspace_id": "demo", "actor_id": "recruiter", "job_id": "role-1"
        },
        finish_ranking=lambda *args: calls.append(("finished", args)),
        fail_ranking=lambda *args: calls.append(("failed", args)),
        update_ranking_progress=lambda *args: calls.append(("progress", args)),
    )
    profile = {"job_id": "role-1", "status": "approved"}
    pipeline = SimpleNamespace(
        repo=SimpleNamespace(get_job_profile=lambda value: profile),
        rank=lambda job_id, approved, top_k, scope, progress: (
            progress("Retrieving candidates") or run_id, ["candidate"]
        ),
    )
    assert AgentRankingWorker(store, pipeline).run_once()
    assert calls == [
        ("progress", (job, "Retrieving candidates")),
        ("finished", (job, run_id, ["candidate"])),
    ]


def test_missing_approved_profile_fails_without_ranking():
    job = {"session_id": uuid4(), "profile_version_id": uuid4(), "top_k": 5, "attempts": 1}
    failed = []
    store = SimpleNamespace(claim_ranking=lambda: job, fail_ranking=lambda item: failed.append(item))
    pipeline = SimpleNamespace(repo=SimpleNamespace(get_job_profile=lambda value: None))
    assert AgentRankingWorker(store, pipeline).run_once()
    assert failed == [job]
