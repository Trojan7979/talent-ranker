from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


def test_dispatch_claims_each_message_only_when_ready_to_send():
    class Repository:
        def __init__(self):
            self.pending = [
                {"id": 1, "recipient_email": "one@example.test", "subject": "One", "body": "A"},
                {"id": 2, "recipient_email": "two@example.test", "subject": "Two", "body": "B"},
            ]
            self.claim_sizes = []
            self.claimed_while_sending = False
            self.sent = []

        def claim_due(self, limit, campaign_id=None):
            self.claim_sizes.append(limit)
            if self.claimed_while_sending:
                raise AssertionError("another message was reserved during a send")
            return [{**self.pending.pop(0), "attempts": 1}] if self.pending else []

        def delivery_still_valid(self, message_id):
            return True

        def mark_delivered(self, message_id, receipt):
            self.sent.append(message_id)

    class Sender(FakeEmailSender):
        def send(self, recipient, subject, body, message_id):
            repo.claimed_while_sending = True
            try:
                return super().send(recipient, subject, body, message_id)
            finally:
                repo.claimed_while_sending = False

    repo = Repository()
    sender = Sender()
    result = InitialInviteDispatcher(repo, sender).run_once(limit=2)
    assert result == {"sent": 2, "failed": 0, "cancelled": 0}
    assert repo.claim_sizes == [1, 1]
    assert repo.sent == [1, 2]
