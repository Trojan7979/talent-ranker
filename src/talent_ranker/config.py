from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "TALENT_RANKER_DATABASE_URL",
        "postgresql://talent_ranker:talent-ranker-local-only@localhost:5432/talent_ranker",
    )
    embedding_model: str = os.getenv(
        "TALENT_RANKER_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
    )
    reranker_model: str = os.getenv("TALENT_RANKER_RERANKER_MODEL", "BAAI/bge-reranker-base")
    retrieval_limit: int = int(os.getenv("TALENT_RANKER_RETRIEVAL_LIMIT", "300"))
    rerank_limit: int = int(os.getenv("TALENT_RANKER_RERANK_LIMIT", "100"))
    rrf_k: int = int(os.getenv("TALENT_RANKER_RRF_K", "60"))
    google_credentials_file: str = os.getenv(
        "TALENT_RANKER_GOOGLE_CREDENTIALS_FILE", "secrets/google-client.json"
    )
    google_token_file: str = os.getenv("TALENT_RANKER_GOOGLE_TOKEN_FILE", ".tokens/drive.json")


SETTINGS = Settings()
