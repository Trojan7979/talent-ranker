"""Agent activation must fail closed without breaking existing service settings."""

import os

import pytest
from pydantic import ValidationError

from sieve_app.agent_config import AgentConfigurationError, AgentSettings


@pytest.fixture(autouse=True)
def isolated_agent_environment(monkeypatch):
    for key in os.environ:
        if key.startswith("SIEVE_AGENT_"):
            monkeypatch.delenv(key)


def settings(**overrides):
    values = {
        "enabled": True,
        "model": "configured-tool-model",
        "api_key": "test-secret",
        "base_url": "https://provider.example/v1",
        "allowed_jobs_by_actor": {"recruiter-1": {"backend-engineer"}},
    }
    return AgentSettings(_env_file=None, **(values | overrides))


def test_agent_is_opt_in_and_secrets_are_not_in_repr():
    disabled = AgentSettings(_env_file=None)
    assert disabled.enabled is False
    with pytest.raises(AgentConfigurationError, match="disabled"):
        disabled.require_ready()
    assert "test-secret" not in repr(settings())


def test_scope_is_explicit_and_unknown_actors_are_denied():
    configured = settings()
    configured.require_ready()
    assert configured.allowed_job_ids("recruiter-1") == frozenset({"backend-engineer"})
    assert configured.allowed_job_ids("someone-else") == frozenset()


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": " "},
        {"api_key": " "},
        {"base_url": ""},
        {"workspace_id": " "},
        {"allowed_jobs_by_actor": {}},
        {"allowed_jobs_by_actor": {"recruiter-1": []}},
        {"allowed_jobs_by_actor": {"": ["job"]}},
        {"allowed_jobs_by_actor": {"recruiter-1": [""]}},
    ],
)
def test_incomplete_configuration_is_rejected_at_activation(overrides):
    configured = settings(**overrides)
    with pytest.raises(AgentConfigurationError, match="Configure"):
        configured.require_ready()


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/v1",
        "https://user:test-secret@provider.example/v1",
        "https://provider.example/v1?key=test-secret",
        "https://provider.example/v1#fragment",
        "https://provider.example:invalid/v1",
        "https://[invalid/v1",
    ],
)
def test_invalid_provider_urls_do_not_leak_credentials(url):
    with pytest.raises(AgentConfigurationError) as error:
        settings(base_url=url).require_ready()
    assert "test-secret" not in str(error.value)


def test_execution_budgets_are_bounded():
    with pytest.raises(ValidationError):
        settings(max_tool_calls=0)
    with pytest.raises(AgentConfigurationError, match="timeout"):
        settings(execution_timeout_seconds=10, model_timeout_seconds=30).require_ready()


def test_environment_scope_parses_and_calibration_key_is_not_reused(monkeypatch):
    monkeypatch.setenv("SIEVE_AGENT_ALLOWED_JOBS_BY_ACTOR", '{"recruiter-2":["job-2"]}')
    monkeypatch.setenv("TALENT_RANKER_CALIBRATION_API_KEY", "unrelated-secret")
    configured = AgentSettings(_env_file=None)
    assert configured.allowed_job_ids("recruiter-2") == frozenset({"job-2"})
    assert configured.api_key is None
