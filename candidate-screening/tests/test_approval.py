import pytest
from conftest import RUN_ID, headers, make_config


def proposal(client):
    config_id = make_config(client)
    response = client.post(
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
    assert response.status_code == 201, response.text
    return response.json()


def set_contact(client, candidate_id):
    response = client.put(
        f"/screening/candidates/{candidate_id}/contact",
        headers=headers(),
        json={"email": f"{candidate_id.lower()}@example.test", "source": "ats"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.integration
def test_approval_requires_all_contacts_and_queues_exactly_once(client):
    campaign = proposal(client)
    set_contact(client, "CAND_0001")
    approve_url = f"/screening/campaigns/{campaign['id']}/approve"
    blocked = client.post(approve_url, headers=headers(), json={"expected_revision": 1})
    assert blocked.status_code == 409
    assert "CAND_0003" in blocked.json()["detail"]
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_invites")
        assert cur.fetchone()["count"] == 0
    set_contact(client, "CAND_0003")
    approved = client.post(approve_url, headers=headers(), json={"expected_revision": 1})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] == "recruiter-1"
    assert approved.json()["final_candidate_ids"] == ["CAND_0001", "CAND_0003"]
    repeated = client.post(approve_url, headers=headers(), json={"expected_revision": 1})
    assert repeated.status_code == 200
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT i.candidate_id,i.token,i.status,o.body,o.status AS delivery_status
               FROM screening_invites i JOIN screening_delivery_outbox o ON o.invite_id=i.id"""
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert len({row["token"] for row in rows}) == 2
    assert all(row["status"] is None and row["delivery_status"] == "pending" for row in rows)
    assert all(row["token"] in row["body"] for row in rows)
    assert (
        client.post(
            f"/screening/campaigns/{campaign['id']}/reject?expected_revision=2", headers=headers()
        ).status_code
        == 409
    )


@pytest.mark.integration
def test_recruiter_edit_is_final_membership(client):
    campaign = proposal(client)
    set_contact(client, "CAND_0001")
    edited = client.patch(
        f"/screening/campaigns/{campaign['id']}",
        headers=headers(),
        json={
            "expected_revision": 1,
            "final_candidate_ids": ["CAND_0001"],
            "message_template": "One link: {screening_link}",
        },
    )
    assert edited.status_code == 200
    approved = client.post(
        f"/screening/campaigns/{campaign['id']}/approve",
        headers=headers(),
        json={"expected_revision": 2},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["final_candidate_ids"] == ["CAND_0001"]
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT candidate_id FROM screening_invites")
        assert [row["candidate_id"] for row in cur.fetchall()] == ["CAND_0001"]
