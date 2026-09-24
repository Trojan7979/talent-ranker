from candidate_screening.email import SmtpEmailSender


def test_smtp_adapter_uses_tls_and_stable_message_identity(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def starttls(self):
            calls.append("tls")

        def login(self, username, password):
            calls.append((username, password))

        def send_message(self, message):
            calls.append((message["To"], message["Message-ID"], message.get_content()))
            return {}

    monkeypatch.setattr("candidate_screening.email.smtplib.SMTP", FakeSMTP)
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=587,
        from_email="hiring@example.test",
        username="account",
        password="secret",
    )
    assert (
        sender.send("candidate@example.test", "Screening", "Your link", "message-1") == "message-1"
    )
    assert calls[0] == ("smtp.example.test", 587, 15)
    assert calls[1] == "tls"
    assert calls[2] == ("account", "secret")
    assert calls[3][1] == "<message-1@screening.local>"
