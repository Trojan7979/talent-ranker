from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sieve_app.agent_views import view


def test_ranking_progress_reaches_recruiter_session_response():
    session_id = uuid4()
    store = SimpleNamespace(
        repository=object(),
        ranking_job=lambda _: {
            "status": "running", "progress_message": "Retrieved 27 candidates",
            "progress_events": ["Preparing ranking", "Retrieved 27 candidates"],
        },
        messages=lambda _: [],
    )
    session = view(store, {
        "id": session_id, "job_id": "role-1", "ranking_run_id": None,
        "campaign_id": None, "setup_stage": "ranking",
        "created_at": datetime.now(timezone.utc),
    }, object())

    assert session.ranking_status == "running"
    assert session.ranking_progress == "Retrieved 27 candidates"
    assert session.ranking_events == ["Preparing ranking", "Retrieved 27 candidates"]
