from types import SimpleNamespace
from uuid import uuid4

import pytest

from sieve_app import agent_api


def test_delete_session_uses_signed_in_recruiter_scope(monkeypatch):
    session_id = uuid4()
    calls = []

    class Store:
        def delete_session(self, requested, workspace, recruiter_id):
            calls.append((requested, workspace, recruiter_id))
            return recruiter_id == "signed-in-recruiter"

    settings = SimpleNamespace(workspace_id="production-workspace")
    monkeypatch.setattr(
        agent_api, "services", lambda request: (settings, None, None, Store())
    )
    request = SimpleNamespace()

    assert agent_api.delete_session(
        session_id, "signed-in-recruiter", request
    ) is None
    assert calls[-1] == (session_id, "production-workspace", "signed-in-recruiter")

    with pytest.raises(agent_api.HTTPException) as hidden:
        agent_api.delete_session(session_id, "another-recruiter", request)
    assert hidden.value.status_code == 404
