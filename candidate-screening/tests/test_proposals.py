import pytest
from conftest import RUN_ID, headers, make_config


@pytest.mark.integration
def test_proposals_pin_run_and_never_send(client):
    assert client.post("/screening/selections", json={}).status_code == 401
    config_id = make_config(client)
    contact = client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "person@example.test", "source": "ats"},
    )
    assert contact.status_code == 200, contact.text
    request = {
        "job_id": "job-1",
        "ranking_run_id": str(RUN_ID),
        "rule": {"kind": "top_n", "value": 2},
    }
    preview = client.post("/screening/selections", headers=headers(), json=request)
    assert preview.status_code == 200, preview.text
    assert [item["candidate_id"] for item in preview.json()["candidates"]] == [
        "CAND_0001",
        "CAND_0003",
    ]
    assert [item["has_contact"] for item in preview.json()["candidates"]] == [True, False]
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={**request, "config_id": config_id, "message_template": "Hello, use {screening_link}"},
    )
    assert proposed.status_code == 201, proposed.text
    campaign = proposed.json()
    assert campaign["status"] == "proposed"
    assert campaign["proposed_candidate_ids"] == ["CAND_0001", "CAND_0003"]
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_invites")
        assert cur.fetchone()["count"] == 0
    edited = client.patch(
        f"/screening/campaigns/{campaign['id']}",
        headers=headers(),
        json={
            "expected_revision": 1,
            "final_candidate_ids": ["CAND_0003", "CAND_0001"],
            "message_template": "Hi {screening_link}",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["final_candidate_ids"] == ["CAND_0003", "CAND_0001"]
    assert (
        client.patch(
            f"/screening/campaigns/{campaign['id']}",
            headers=headers(),
            json={
                "expected_revision": 1,
                "final_candidate_ids": ["CAND_0001"],
                "message_template": "Hi {screening_link}",
            },
        ).status_code
        == 409
    )
    rejected = client.post(
        f"/screening/campaigns/{campaign['id']}/reject?expected_revision=2", headers=headers()
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.integration
def test_selector_boundaries_and_invalid_membership(client):
    config_id = make_config(client)
    base = {"job_id": "job-1", "ranking_run_id": str(RUN_ID)}
    for rule, expected in [
        ({"kind": "score_threshold", "value": 0.8}, ["CAND_0001"]),
        ({"kind": "rank_cutoff", "value": 2}, ["CAND_0001"]),
        ({"kind": "top_n", "value": 2}, ["CAND_0001", "CAND_0003"]),
    ]:
        response = client.post(
            "/screening/selections", headers=headers(), json={**base, "rule": rule}
        )
        assert response.status_code == 200, response.text
        assert [item["candidate_id"] for item in response.json()["candidates"]] == expected
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            **base,
            "rule": {"kind": "top_n", "value": 2},
            "config_id": config_id,
            "message_template": "Hi {screening_link}",
        },
    ).json()
    invalid = client.patch(
        f"/screening/campaigns/{proposed['id']}",
        headers=headers(),
        json={
            "expected_revision": 1,
            "final_candidate_ids": ["CAND_0002"],
            "message_template": "Hi {screening_link}",
        },
    )
    assert invalid.status_code == 409


@pytest.mark.integration
def test_screening_questions_must_cover_approved_must_haves(client):
    from conftest import PROFILE_ID

    response = client.post(
        "/screening/jobs/job-1/configs",
        headers=headers(),
        json={
            "job_profile_version_id": str(PROFILE_ID),
            "questions": {"version": 1, "must_haves": [{"id": "java", "text": "Java"}]},
        },
    )
    assert response.status_code == 409
    assert "approved hiring criteria" in response.json()["detail"]
