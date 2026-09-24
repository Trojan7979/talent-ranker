"""Exercise the planned two-Gmail/two-Outlook recipient mix without live sending."""

import pytest
from conftest import RUN_ID, headers, make_config

from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


@pytest.mark.integration
def test_four_mixed_mailbox_recipients_receive_unique_mock_links(client):
    contacts = {
        "CAND_0001": "mock-gmail-one@gmail.invalid",
        "CAND_0003": "mock-gmail-two@gmail.invalid",
        "CAND_0004": "mock-outlook-one@outlook.invalid",
        "CAND_0005": "mock-outlook-two@outlook.invalid",
    }
    for candidate_id, email in contacts.items():
        response = client.put(
            f"/screening/candidates/{candidate_id}/contact",
            headers=headers(),
            json={"email": email, "source": "mock-fixture"},
        )
        assert response.status_code == 200, response.text

    config_id = make_config(client)
    proposal = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": config_id,
            "rule": {"kind": "top_n", "value": 4},
            "message_template": "Complete screening: {screening_link}",
        },
    )
    assert proposal.status_code == 201, proposal.text
    campaign_id = proposal.json()["id"]
    assert proposal.json()["proposed_candidate_ids"] == list(contacts)
    approved = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approved.status_code == 200, approved.text

    sender = FakeEmailSender()
    counts = InitialInviteDispatcher(client.app.state.repo, sender).run_once()
    assert counts == {"sent": 4, "failed": 0, "cancelled": 0}
    assert {recipient for recipient, _, _, _ in sender.sent} == set(contacts.values())
    links = [body for _, _, body, _ in sender.sent]
    assert len(set(links)) == 4
    assert InitialInviteDispatcher(client.app.state.repo, sender).run_once()["sent"] == 0
