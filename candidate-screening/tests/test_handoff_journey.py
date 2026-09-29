"""A synthetic recruiter-to-candidate handoff across the real screening API and SQL."""

from io import BytesIO

from conftest import RUN_ID, headers, make_config
from openpyxl import load_workbook
from test_candidate_flow import complete_answers

from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


def test_saved_ranking_run_reaches_recruiter_review_and_export(client):
    config_id = make_config(client)
    assert (
        client.put(
            "/screening/candidates/CAND_0001/contact",
            headers=headers(),
            json={"email": "candidate@example.test", "source": "test"},
        ).status_code
        == 200
    )
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": config_id,
            "rule": {"kind": "top_n", "value": 1},
            "message_template": "Please complete {screening_link}",
        },
    )
    assert proposed.status_code == 201, proposed.text
    campaign_id = proposed.json()["id"]
    directory = client.get("/screening/campaigns", headers=headers())
    assert campaign_id in {item["id"] for item in directory.json()["items"]}

    approval = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approval.status_code == 200, approval.text
    sender = FakeEmailSender()
    dispatcher = InitialInviteDispatcher(client.app.state.repo, sender)
    assert dispatcher.run_once() == {"sent": 1, "failed": 0, "cancelled": 0}
    assert dispatcher.run_once()["sent"] == 0
    assert len(sender.sent) == 1

    activity_url = f"/screening/campaigns/{campaign_id}/invites"
    activity = client.get(activity_url, headers=headers()).json()["items"]
    assert len(activity) == 1
    assert activity[0]["candidate_id"] == "CAND_0001"
    assert activity[0]["delivery_status"] == "sent"
    assert "token" not in activity[0]

    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT token FROM screening_invites WHERE campaign_id=%s", (campaign_id,))
        token = cur.fetchone()["token"]
    invite_url = f"/screening/invites/{token}"
    assert client.get(invite_url).status_code == 200
    assert client.post(invite_url + "/opened").status_code == 200
    assert client.post(invite_url + "/started").status_code == 200
    draft = client.put(
        invite_url + "/responses",
        json={"expected_revision": 0, "answers": {"interest": "interested"}},
    )
    assert draft.status_code == 200, draft.text
    completed = client.post(
        invite_url + "/complete",
        json={"expected_revision": 1, "answers": complete_answers()},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["outcome"] == "proceed_to_interview"

    review = client.get(f"/screening/campaigns/{campaign_id}/results", headers=headers())
    assert review.status_code == 200, review.text
    assert review.json()["counts"]["proceed_to_interview"] == 1
    assert review.json()["items"][0]["id"] == completed.json()["id"]
    assert client.get(activity_url, headers=headers()).json()["items"][0]["status"] == "completed"

    exported = client.post(
        f"/screening/campaigns/{campaign_id}/exports",
        headers=headers(),
        json={"candidate_ids": ["CAND_0001"]},
    )
    assert exported.status_code == 200, exported.text
    workbook = load_workbook(BytesIO(exported.content), read_only=True)
    assert workbook.active.max_row == 2
