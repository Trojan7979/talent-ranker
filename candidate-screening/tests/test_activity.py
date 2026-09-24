import pytest
from conftest import headers
from test_candidate_flow import complete_answers
from test_review import sent_batch


@pytest.mark.integration
def test_recruiter_roster_tracks_candidate_lifecycle_without_tokens(client):
    campaign_id, tokens = sent_batch(client)
    url = f"/screening/campaigns/{campaign_id}/invites"
    assert client.get(url).status_code == 401

    first = client.get(url, headers=headers(), params={"limit": 1})
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 1
    assert first.json()["next_cursor"] == "CAND_0001"
    assert first.json()["items"][0]["delivery_status"] == "sent"
    assert first.json()["items"][0]["status"] == "sent"
    assert "token" not in first.json()["items"][0]

    second = client.get(
        url, headers=headers(), params={"after": first.json()["next_cursor"], "limit": 1}
    )
    assert [item["candidate_id"] for item in second.json()["items"]] == ["CAND_0003"]
    assert second.json()["next_cursor"] is None

    invite_url = f"/screening/invites/{tokens['CAND_0001']}"
    assert client.post(f"{invite_url}/opened").status_code == 200
    assert client.get(url, headers=headers()).json()["items"][0]["status"] == "opened"
    assert client.post(f"{invite_url}/started").status_code == 200
    assert (
        client.post(
            f"{invite_url}/complete",
            json={"expected_revision": 0, "answers": complete_answers()},
        ).status_code
        == 200
    )
    assert client.get(url, headers=headers()).json()["items"][0]["status"] == "completed"
