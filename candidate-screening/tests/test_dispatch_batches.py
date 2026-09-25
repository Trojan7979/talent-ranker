from uuid import UUID, uuid4

from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.email import FakeEmailSender


class QueueRepository:
    def __init__(self, count: int):
        self.messages = [
            {
                "id": uuid4(),
                "recipient_email": f"candidate-{index}@example.test",
                "subject": "Screening",
                "body": "Link",
                "attempts": 1,
            }
            for index in range(count)
        ]
        self.claim_sizes: list[int] = []
        self.delivered: list[UUID] = []

    def claim_due(self, limit: int, campaign_id: UUID):
        self.claim_sizes.append(limit)
        claimed, self.messages = self.messages[:limit], self.messages[limit:]
        return claimed

    def delivery_still_valid(self, message_id: UUID) -> bool:
        return True

    def mark_delivered(self, message_id: UUID, receipt: str) -> None:
        self.delivered.append(message_id)


def test_campaign_dispatch_drains_more_than_one_claim_without_duplicate_mail():
    repo = QueueRepository(205)
    sender = FakeEmailSender()
    counts = InitialInviteDispatcher(repo, sender).run_campaign(uuid4(), 205)

    assert counts == {"sent": 205, "failed": 0, "cancelled": 0}
    assert repo.claim_sizes == [100, 100, 5]
    assert len(set(repo.delivered)) == len(sender.sent) == 205
