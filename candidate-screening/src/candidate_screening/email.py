from collections.abc import Mapping
from dataclasses import dataclass, field
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
