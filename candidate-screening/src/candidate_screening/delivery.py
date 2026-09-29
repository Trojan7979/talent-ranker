import smtplib
from uuid import UUID

from .email import EmailSender


class InitialInviteDispatcher:
    def __init__(self, repository, sender: EmailSender):
        self.repo = repository
        self.sender = sender

    def run_once(self, limit: int = 100, campaign_id: UUID | None = None) -> dict[str, int]:
        counts = {"sent": 0, "failed": 0, "cancelled": 0}
        for _ in range(limit):
            claimed = self.repo.claim_due(1, campaign_id=campaign_id)
            if not claimed:
                break
            message = claimed[0]
            if not self.repo.delivery_still_valid(message["id"]):
                self.repo.cancel_delivery(message["id"])
                counts["cancelled"] += 1
                continue
            try:
                receipt = self.sender.send(
                    message["recipient_email"],
                    message["subject"],
                    message["body"],
                    str(message["id"]),
                )
            except (OSError, RuntimeError, smtplib.SMTPException) as error:
                self.repo.mark_delivery_failed(
                    message["id"], type(error).__name__, message["attempts"]
                )
                counts["failed"] += 1
            else:
                self.repo.mark_delivered(message["id"], receipt)
                counts["sent"] += 1
        return counts

    def run_campaign(self, campaign_id: UUID, max_messages: int) -> dict[str, int]:
        """Drain due initial invitations in bounded claims for one approved batch."""
        totals = {"sent": 0, "failed": 0, "cancelled": 0}
        remaining = max_messages
        while remaining > 0:
            limit = min(100, remaining)
            counts = self.run_once(limit, campaign_id)
            processed = sum(counts.values())
            for state, count in counts.items():
                totals[state] += count
            remaining -= processed
            if processed < limit:
                break
        return totals
