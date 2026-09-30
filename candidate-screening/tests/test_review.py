import pytest
from conftest import RUN_ID, headers, make_config
from test_candidate_flow import complete_answers

from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


def sent_batch(client):
    config_id = make_config(client)
    for candidate_id in ("CAND_0001", "CAND_0003"):
        response = client.put(
            f"/screening/candidates/{candidate_id}/contact",
            headers=headers(),
            json={"email": f"{candidate_id.lower()}@example.test", "source": "ats"},
        )
        assert response.status_code == 200
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": config_id,
            "rule": {"kind": "top_n", "value": 2},
            "message_template": "Hello {screening_link}",
        },
    )
    assert proposed.status_code == 201, proposed.text
    campaign_id = proposed.json()["id"]
    assert (
        client.post(
            f"/screening/campaigns/{campaign_id}/approve",
            headers=headers(),
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    sender = FakeEmailSender()
    assert InitialInviteDispatcher(client.app.state.repo, sender).run_once()["sent"] == 2
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT candidate_id,token FROM screening_invites WHERE campaign_id=%s", (campaign_id,)
        )
        tokens = {row["candidate_id"]: row["token"] for row in cur.fetchall()}
    return campaign_id, tokens


@pytest.mark.integration
def test_same_ranking_run_can_start_fresh_campaign_without_resetting_results(client):
    first_id, first_tokens = sent_batch(client)
    first_token = first_tokens["CAND_0001"]
    assert client.post(f"/screening/invites/{first_token}/started").status_code == 200
    completed = client.post(
        f"/screening/invites/{first_token}/complete",
        json={"expected_revision": 0, "answers": complete_answers()},
    )
    assert completed.status_code == 200, completed.text

    first = client.get(f"/screening/campaigns/{first_id}", headers=headers()).json()
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": first["job_id"],
            "ranking_run_id": first["ranking_run_id"],
            "config_id": first["config_id"],
            "rule": first["selection_rule"],
            "message_template": first["message_template"],
        },
    )
    assert proposed.status_code == 201, proposed.text
    second_id = proposed.json()["id"]
    approved = client.post(
        f"/screening/campaigns/{second_id}/approve",
        headers=headers(), json={"expected_revision": 1},
    )
    assert approved.status_code == 200, approved.text

    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT candidate_id, token, status FROM screening_invites WHERE campaign_id=%s",
            (second_id,),
        )
        fresh = {row["candidate_id"]: row for row in cur.fetchall()}
        cur.execute(
            """SELECT o.status FROM screening_delivery_outbox o
               JOIN screening_invites i ON i.id=o.invite_id WHERE i.campaign_id=%s""",
            (second_id,),
        )
        delivery_statuses = [row["status"] for row in cur.fetchall()]
    assert set(fresh) == set(first_tokens)
    assert all(fresh[candidate_id]["token"] != token for candidate_id, token in first_tokens.items())
    assert all(row["status"] is None for row in fresh.values())
    assert delivery_statuses == ["pending"] * len(first_tokens)
    results = client.get(f"/screening/campaigns/{first_id}/results", headers=headers())
    assert results.status_code == 200
    assert results.json()["items"][0]["candidate_id"] == "CAND_0001"


@pytest.mark.integration
def test_review_first_paginated_and_filterable(client):
    campaign_id, tokens = sent_batch(client)
    results_url = f"/screening/campaigns/{campaign_id}/results"
    assert client.get(results_url).status_code == 401
    for candidate_id, answers in [
        ("CAND_0001", complete_answers()),
        ("CAND_0003", {"interest": "interested"}),
    ]:
        token = tokens[candidate_id]
        assert client.post(f"/screening/invites/{token}/started").status_code == 200
        response = client.post(
            f"/screening/invites/{token}/complete",
            json={"expected_revision": 0, "answers": answers},
        )
        assert response.status_code == 200, response.text
    first = client.get(results_url, headers=headers(), params={"limit": 1})
    assert first.status_code == 200, first.text
    assert first.json()["counts"] == {
        "proceed_to_interview": 1,
        "needs_recruiter_review": 1,
        "do_not_proceed": 0,
    }
    assert first.json()["items"][0]["candidate_id"] == "CAND_0003"
    assert first.json()["next_cursor"]
    assert "token" not in first.json()["items"][0]
    second = client.get(
        results_url,
        headers=headers(),
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["candidate_id"] == "CAND_0001"
    assert second.json()["next_cursor"] is None
    chronological = client.get(
        results_url, headers=headers(), params={"sort_by": "completed_at", "limit": 1}
    )
    assert chronological.status_code == 200
    assert chronological.json()["items"][0]["candidate_id"] == "CAND_0001"
    filtered = client.get(
        results_url, headers=headers(), params={"outcome": "needs_recruiter_review"}
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    summary_id = first.json()["items"][0]["id"]
    detail = client.get(f"/screening/summaries/{summary_id}", headers=headers())
    assert detail.status_code == 200
    assert "salary" in detail.json()["missing"]
    assert (
        client.get(results_url, headers=headers(), params={"cursor": "garbage"}).status_code == 422
    )
