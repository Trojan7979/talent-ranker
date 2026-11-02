from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TALENT_RANKER_",
        extra="ignore",
    )

    database_url: str = ""
    hosted_embedding_model: str = ""
    hosted_reranker_model: str = ""
    hosted_embedding_url: str = ""
    hosted_reranker_url: str = ""
    hosted_model_timeout_seconds: float = 60.0
    retrieval_limit: int = 300
    rerank_limit: int = 100
    rrf_k: int = 60
    calibration_extractor: Literal["rules", "llm", "hybrid"] = "rules"
    calibration_api_url: str = ""
    calibration_api_key: SecretStr | None = None
    calibration_model: str = ""
    calibration_timeout_seconds: float = 60.0
    google_credentials_file: str = "secrets/google-client.json"
    google_token_file: str = ".tokens/drive.json"
    google_web_credentials_file: str = "candidate-screening/secrets/gmail-web-client.json"
    google_web_redirect_uri: str = ""
    frontend_base_url: str = ""
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: SecretStr | None = None
    github_token: SecretStr | None = None
    canonical_storage_backend: str = "s3"
    canonical_s3_bucket: str = ""
    canonical_s3_prefix: str = "talent-ranker"
    canonical_s3_endpoint_url: str | None = None
    canonical_local_root: str = ".data/object-storage"
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


SETTINGS = Settings()
