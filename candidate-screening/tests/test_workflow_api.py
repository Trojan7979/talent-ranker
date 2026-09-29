from conftest import RUN_ID, headers, make_config
from langgraph.checkpoint.memory import InMemorySaver
from sieve_app.workflow import CampaignWorkflow


def test_workflow_observes_existing_approval_and_requires_recruiter(client):
    config_id = make_config(client)
    client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "candidate@example.test", "source": "test"},
    )
    proposal = client.post(
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
    assert proposal.status_code == 201, proposal.text
    campaign_id = proposal.json()["id"]
    path = f"/screening/campaigns/{campaign_id}/workflow"
    assert client.post(path + "/sync").status_code == 401
    assert client.post(path + "/sync", headers=headers()).status_code == 503

    client.app.state.workflow = CampaignWorkflow(client.app.state.repo, InMemorySaver())
    first = client.post(path + "/sync", headers=headers())
    assert first.status_code == 200, first.text
    assert first.json()["workflow_status"] == "waiting_for_recruiter"
    assert client.get(path, headers=headers()).json() == first.json()

    approval = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approval.status_code == 200, approval.text
    final = client.get(path, headers=headers())
    assert final.status_code == 200, final.text
    assert final.json()["workflow_status"] == "observed"
    assert final.json()["campaign_status"] == "approved"
