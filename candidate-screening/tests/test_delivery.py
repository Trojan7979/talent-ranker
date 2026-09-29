from uuid import UUID

import pytest
from conftest import RUN_ID, headers, make_config

from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


def approved_campaign(client):
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
            "message_template": "Link {screening_link}",
        },
    )
    assert proposed.status_code == 201
    campaign_id = proposed.json()["id"]
    approved = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approved.status_code == 200, approved.text
    return campaign_id


@pytest.mark.integration
def test_dispatch_sends_each_queued_link_once(client):
    approved_campaign(client)
    sender = FakeEmailSender()
    dispatcher = InitialInviteDispatcher(client.app.state.repo, sender)
    assert dispatcher.run_once() == {"sent": 2, "failed": 0, "cancelled": 0}
    assert dispatcher.run_once() == {"sent": 0, "failed": 0, "cancelled": 0}
    assert len(sender.sent) == 2
    assert len({message[3] for message in sender.sent}) == 2
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status,sent_at FROM screening_invites")
        assert all(row["status"] == "sent" and row["sent_at"] for row in cur.fetchall())


@pytest.mark.integration
def test_provider_error_holds_invitation_without_automatic_resend(client):
    approved_campaign(client)

    class FailingSender:
        def send(self, recipient, subject, body, message_id):
            raise OSError("provider unavailable")

    repo = client.app.state.repo
    assert InitialInviteDispatcher(repo, FailingSender()).run_once()["failed"] == 2
    with repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status,last_error FROM screening_delivery_outbox")
        assert all(
            row == {"status": "unknown", "last_error": "OSError"} for row in cur.fetchall()
        )
    sender = FakeEmailSender()
    assert InitialInviteDispatcher(repo, sender).run_once()["sent"] == 0
    assert sender.sent == []


@pytest.mark.integration
def test_expired_send_lease_is_held_for_reconciliation(client):
    approved_campaign(client)
    repo = client.app.state.repo
    assert len(repo.claim_due(1)) == 1
    with repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE screening_delivery_outbox SET leased_until=now()-interval '1 minute' "
            "WHERE status='processing'"
        )
    sender = FakeEmailSender()
    assert InitialInviteDispatcher(repo, sender).run_once()["sent"] == 1
    assert len(sender.sent) == 1
    with repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status,last_error FROM screening_delivery_outbox")
        rows = cur.fetchall()
    assert sum(row["status"] == "unknown" and row["last_error"] == "send_lease_expired" for row in rows) == 1


@pytest.mark.integration
def test_expired_or_deleted_candidate_is_not_dispatched(client):
    approved_campaign(client)
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE screening_invites SET expires_at=now()-interval '1 minute'
               WHERE candidate_id='CAND_0001'"""
        )
        cur.execute("UPDATE candidates SET deleted_at=now() WHERE candidate_id='CAND_0003'")
    sender = FakeEmailSender()
    assert InitialInviteDispatcher(client.app.state.repo, sender).run_once()["sent"] == 0
    assert sender.sent == []


@pytest.mark.integration
def test_dispatch_can_be_limited_to_one_approved_campaign(client):
    first_id = approved_campaign(client)
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM screening_job_configs WHERE job_id='job-1'")
        config_id = cur.fetchone()["id"]
    second = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": str(config_id),
            "rule": {"kind": "top_n", "value": 2},
            "message_template": "Second {screening_link}",
        },
    )
    assert second.status_code == 201
    second_id = second.json()["id"]
    assert (
        client.post(
            f"/screening/campaigns/{second_id}/approve",
            headers=headers(),
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    sender = FakeEmailSender()
    dispatcher = InitialInviteDispatcher(client.app.state.repo, sender)
    assert dispatcher.run_once(campaign_id=UUID(first_id))["sent"] == 2
    assert len(sender.sent) == 2
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) AS count FROM screening_delivery_outbox o
               JOIN screening_invites i ON i.id=o.invite_id
               WHERE i.campaign_id=%s AND o.status='pending'""",
            (second_id,),
        )
        assert cur.fetchone()["count"] == 2
