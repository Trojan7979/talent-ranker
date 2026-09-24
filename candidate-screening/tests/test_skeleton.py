from fastapi.testclient import TestClient

from candidate_screening.api import create_app
from candidate_screening.config import Settings
from candidate_screening.email import FakeContactResolver, FakeEmailSender


def test_standalone_health_and_openapi() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "candidate-screening"}
    assert "screening_health" in str(client.get("/openapi.json").json())


def test_io_ports_are_replaceable() -> None:
    sender = FakeEmailSender()
    contact = FakeContactResolver({"CAND_0001": "candidate@example.test"})
    assert sender.send(contact.resolve("CAND_0001"), "Hi", "Link", "message-1") == "message-1"
    assert len(sender.sent) == 1
    assert Settings().invite_expiry_hours == 48
