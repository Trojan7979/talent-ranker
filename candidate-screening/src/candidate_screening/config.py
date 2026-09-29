from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCREENING_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql://talent_ranker:talent-ranker-local@localhost:5432/talent_ranker"
    )
    public_base_url: str = "http://localhost:8001/screening/invites"
    api_port: int = Field(default=8001, ge=1, le=65535)
    invite_expiry_hours: int = Field(default=48, ge=1, le=720)
    max_campaign_size: int = Field(default=1000, ge=1, le=10000)
    sender_backend: str = "fake"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    gmail_sender_email: str | None = None
    gmail_client_secrets_file: Path | None = None
    gmail_token_file: Path = Path(".tokens/gmail-sender.json")
    gmail_web_client_secrets_file: Path = Path("secrets/gmail-web-client.json")
    gmail_web_redirect_uri: str = "http://127.0.0.1:8001/screening/oauth/gmail/callback"
    frontend_base_url: str = "http://127.0.0.1:5173"
    recruiter_tokens: dict[str, str] = Field(default_factory=dict)
    workflow_enabled: bool = False
