import smtplib

from .email import EmailSender


class InitialInviteDispatcher:
    def __init__(self, repository, sender: EmailSender):
        self.repo = repository
        self.sender = sender

    def run_once(self, limit: int = 100) -> dict[str, int]:
        counts = {"sent": 0, "failed": 0, "cancelled": 0}
        for message in self.repo.claim_due(limit):
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
