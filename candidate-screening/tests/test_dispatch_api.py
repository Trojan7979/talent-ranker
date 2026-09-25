from pathlib import Path

from conftest import RUN_ID, headers, make_config


def test_recruiter_dispatches_only_approved_campaign_once(client):
    client.app.state.settings.sender_backend = "fake"
    config_id = make_config(client)
    contact = client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "candidate@example.test", "source": "test"},
    )
    assert contact.status_code == 200
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": config_id,
            "rule": {"kind": "top_n", "value": 1},
            "message_template": "Hello {screening_link}",
        },
    )
    assert proposed.status_code == 201
    campaign_id = proposed.json()["id"]
    path = f"/screening/campaigns/{campaign_id}/dispatch"

    assert client.post(path).status_code == 401
    assert client.post(path, headers=headers()).status_code == 409
    approved = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approved.status_code == 200

    client.app.state.settings.sender_backend = "gmail_api"
    client.app.state.settings.gmail_sender_email = "sender@example.test"
    client.app.state.settings.gmail_token_file = Path("missing-gmail-token.json")
    assert client.post(path, headers=headers()).status_code == 503
    queued = client.get(f"/screening/campaigns/{campaign_id}/invites", headers=headers())
    assert queued.json()["items"][0]["delivery_status"] == "pending"
    client.app.state.settings.sender_backend = "fake"

    first = client.post(path, headers=headers())
    assert first.status_code == 202
    assert first.json() == {"campaign_id": campaign_id, "status": "scheduled"}
    assert client.post(path, headers=headers()).status_code == 202
    activity = client.get(f"/screening/campaigns/{campaign_id}/invites", headers=headers())
    assert activity.status_code == 200
    assert len(activity.json()["items"]) == 1
    assert activity.json()["items"][0]["delivery_status"] == "sent"
