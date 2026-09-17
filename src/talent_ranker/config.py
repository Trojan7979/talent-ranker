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
    google_credentials_file: str = "secrets/google-client.json"
    google_token_file: str = ".tokens/drive.json"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


SETTINGS = Settings()
