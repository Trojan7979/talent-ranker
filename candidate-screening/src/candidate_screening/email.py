import smtplib
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol


class EmailSender(Protocol):
    def send(self, recipient: str, subject: str, body: str, message_id: str) -> str: ...


class ContactResolver(Protocol):
    def resolve(self, candidate_id: str) -> str | None: ...


@dataclass
class FakeEmailSender:
    sent: list[tuple[str, str, str, str]] = field(default_factory=list)

    def send(self, recipient: str, subject: str, body: str, message_id: str) -> str:
        self.sent.append((recipient, subject, body, message_id))
        return message_id


@dataclass
class FakeContactResolver:
    contacts: Mapping[str, str]

    def resolve(self, candidate_id: str) -> str | None:
        return self.contacts.get(candidate_id)


@dataclass(frozen=True)
class SmtpEmailSender:
    host: str
    port: int
    from_email: str
    username: str | None = None
    password: str | None = None
    timeout_seconds: int = 15

    def send(self, recipient: str, subject: str, body: str, message_id: str) -> str:
        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = f"<{message_id}@screening.local>"
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("SMTP did not accept every recipient")
        return message_id
