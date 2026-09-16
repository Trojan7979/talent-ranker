from __future__ import annotations

from functools import lru_cache
from typing import Sequence
import numpy as np


class HuggingFaceEncoder:
    def __init__(self, model_name: str):
        self.model_name = model_name

    @property
    @lru_cache(maxsize=1)
    def model(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_name, device="cpu")

    def encode(self, texts: Sequence[str], query: bool = False) -> np.ndarray:
        prefix = "Represent this sentence for searching relevant passages: " if query else ""
        values = [prefix + text for text in texts]
        return self.model.encode(
            values, batch_size=64, normalize_embeddings=True, show_progress_bar=False
        )


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        self.model_name = model_name

    @property
    @lru_cache(maxsize=1)
    def model(self):
        from sentence_transformers import CrossEncoder

        return CrossEncoder(self.model_name, device="cpu", max_length=512)

    def score(self, jd: str, documents: Sequence[str]) -> np.ndarray:
        pairs = [(jd, doc) for doc in documents]
        return np.asarray(self.model.predict(pairs, batch_size=32, show_progress_bar=False))
