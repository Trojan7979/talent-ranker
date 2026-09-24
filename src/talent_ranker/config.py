from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TALENT_RANKER_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql://talent_ranker:talent-ranker-local@localhost:5432/talent_ranker"
    )
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieval_limit: int = 300
    rerank_limit: int = 100
    rrf_k: int = 60
    calibration_extractor: Literal["rules", "llm"] = "rules"
    calibration_api_url: str = "https://platform.qubrid.com/v1/chat/completions"
    calibration_api_key: SecretStr | None = None
    calibration_model: str = "deepseek-ai/DeepSeek-V4-Pro"
    calibration_timeout_seconds: float = 60.0
    google_credentials_file: str = "secrets/google-client.json"
    google_token_file: str = ".tokens/drive.json"
    canonical_storage_backend: str = "s3"
    canonical_s3_bucket: str = ""
    canonical_s3_prefix: str = "talent-ranker"
    canonical_s3_endpoint_url: str | None = None
    canonical_local_root: str = ".data/object-storage"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


SETTINGS = Settings()
