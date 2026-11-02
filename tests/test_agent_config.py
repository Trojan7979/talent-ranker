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
        "workspace_id": "test-workspace",
    }
    return AgentSettings(_env_file=None, **(values | overrides))


def test_agent_is_opt_in_and_secrets_are_not_in_repr():
    disabled = AgentSettings(_env_file=None)
    assert disabled.enabled is False
    with pytest.raises(AgentConfigurationError, match="disabled"):
        disabled.require_ready()
    assert "test-secret" not in repr(settings())


def test_agent_activation_does_not_need_demo_actor_mappings():
    configured = settings()
    configured.require_ready()
    assert not hasattr(configured, "allowed_jobs_by_actor")


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": " "},
        {"api_key": " "},
        {"base_url": ""},
        {"workspace_id": " "},
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


def test_agent_does_not_accept_environment_actor_mapping_or_calibration_key(monkeypatch):
    monkeypatch.setenv("SIEVE_AGENT_ALLOWED_JOBS_BY_ACTOR", '{"recruiter-2":["job-2"]}')
    monkeypatch.setenv("TALENT_RANKER_CALIBRATION_API_KEY", "unrelated-secret")
    configured = AgentSettings(_env_file=None)
    assert not hasattr(configured, "allowed_jobs_by_actor")
    assert configured.api_key is None
