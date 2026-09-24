import sys

from candidate_screening.server import main


def test_server_uses_configured_port(monkeypatch):
    calls = []
    monkeypatch.setenv("SCREENING_API_PORT", "8123")
    monkeypatch.setattr(sys, "argv", ["candidate-screening-api", "--reload"])
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    main()

    assert calls == [
        (("candidate_screening.api:app",), {"host": "127.0.0.1", "port": 8123, "reload": True})
    ]
