from datetime import UTC, datetime, timedelta

import pytest
from conftest import sent_invite


def complete_answers():
    today = datetime.now(UTC).date()
    return {
        "qualifications": [{"requirement_id": "python", "confirmation": "yes"}],
        "interest": "interested",
        "availability": {
            "status": "answered",
            "earliest_start_date": (today + timedelta(days=14)).isoformat(),
        },
        "notice_period": {"status": "answered", "days": 14},
        "salary": {
            "status": "answered",
            "minimum": "100000",
            "maximum": "120000",
            "currency": "USD",
            "period": "year",
        },
    }


@pytest.mark.integration
def test_open_start_draft_complete_and_idempotent_retry(client):
    _, token = sent_invite(client)
    base = f"/screening/invites/{token}"
    seen = client.get(base)
    assert seen.status_code == 200
    assert seen.json()["status"] == "sent"
    assert seen.json()["questions"]["must_haves"][0]["id"] == "python"
    assert "hard_fail_on_no" not in seen.json()["questions"]["must_haves"][0]
    assert "salary_maximum" not in seen.json()["questions"]
    assert client.post(base + "/opened").json()["status"] == "opened"
    assert client.post(base + "/started").json()["status"] == "started"
    assert client.post(base + "/opened").json()["status"] == "started"
    draft = client.put(
        base + "/responses", json={"expected_revision": 0, "answers": {"interest": "interested"}}
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["revision"] == 1
    payload = {"expected_revision": 1, "answers": complete_answers()}
    finished = client.post(base + "/complete", json=payload)
    assert finished.status_code == 200, finished.text
    assert finished.json()["outcome"] == "proceed_to_interview"
    assert client.post(base + "/complete", json=payload).json()["id"] == finished.json()["id"]
    changed = {"expected_revision": 1, "answers": {**complete_answers(), "interest": "unsure"}}
    assert client.post(base + "/complete", json=changed).status_code == 409
    assert client.post(base + "/decline").status_code == 409
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_summary")
        assert cur.fetchone()["count"] == 1


@pytest.mark.integration
def test_missing_answers_generate_review_summary(client):
    _, token = sent_invite(client)
    base = f"/screening/invites/{token}"
    assert client.post(base + "/started").status_code == 200
    result = client.post(
        base + "/complete", json={"expected_revision": 0, "answers": {"interest": "interested"}}
    )
    assert result.status_code == 200, result.text
    assert result.json()["outcome"] == "needs_recruiter_review"
    assert "salary" in result.json()["missing"]


@pytest.mark.integration
def test_expiry_wins_over_late_answer_and_sweep_is_idempotent(client):
    _, token = sent_invite(client)
    base = f"/screening/invites/{token}"
    assert client.post(base + "/started").status_code == 200
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE screening_invites SET expires_at=now() WHERE token=%s", (token,))
    late = client.post(
        base + "/complete", json={"expected_revision": 0, "answers": complete_answers()}
    )
    assert late.status_code == 410
    assert client.get(base).status_code == 410
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status,expired_at FROM screening_invites WHERE token=%s", (token,))
        row = cur.fetchone()
    assert row["status"] == "expired" and row["expired_at"]
    assert client.app.state.repo.expire_due() == 0


@pytest.mark.integration
def test_decline_is_terminal_and_has_no_completion_summary(client):
    _, token = sent_invite(client)
    base = f"/screening/invites/{token}"
    assert client.post(base + "/decline").json()["status"] == "declined"
    assert client.post(base + "/started").status_code == 409
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_summary")
        assert cur.fetchone()["count"] == 0
