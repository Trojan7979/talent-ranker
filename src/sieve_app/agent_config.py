"""Explicit configuration for the opt-in recruitment agent runtime."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfigurationError(ValueError):
    """The agent cannot start safely with its current configuration."""


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIEVE_AGENT_", env_file=".env", extra="ignore")

    enabled: bool = False
    model: str = ""
    api_key: SecretStr | None = None
    base_url: str = ""
    workspace_id: str = ""
    max_model_turns: int = Field(default=8, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=40)
    execution_timeout_seconds: float = Field(default=90, gt=0, le=300)
    model_timeout_seconds: float = Field(default=30, gt=0, le=120)
    ranking_explanation_timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_recipients: int = Field(default=10, ge=1, le=100)

    @field_validator("model", "base_url", "workspace_id")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    def require_ready(self) -> None:
        """Validate on agent activation, without coupling existing API startup to it."""
        from urllib.parse import urlsplit

        if not self.enabled:
            raise AgentConfigurationError("Recruitment agent is disabled")
        missing = []
        if not self.model:
            missing.append("SIEVE_AGENT_MODEL")
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            missing.append("SIEVE_AGENT_API_KEY")
        if not self.base_url:
            missing.append("SIEVE_AGENT_BASE_URL")
        if not self.workspace_id:
            missing.append("SIEVE_AGENT_WORKSPACE_ID")
        if missing:
            raise AgentConfigurationError("Configure " + ", ".join(missing))

        try:
            url = urlsplit(self.base_url)
            valid_url = (
                url.scheme == "https"
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
            )
            _ = url.port  # Reject malformed ports without exposing the URL in errors.
        except ValueError:
            valid_url = False
        if not valid_url:
            raise AgentConfigurationError(
                "SIEVE_AGENT_BASE_URL must be HTTPS without credentials, query or fragment"
            )
        if self.model_timeout_seconds > self.execution_timeout_seconds:
            raise AgentConfigurationError("Model timeout must not exceed execution timeout")
