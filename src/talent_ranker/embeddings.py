from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import cached_property
from math import isfinite, log

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2, backoff_factor=0.5, status_forcelist=(429, 502, 503, 504), allowed_methods={"POST"}
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class HostedEmbeddingEncoder:
    dimension = 1024
    max_tokens = 512

    def __init__(self, base_url: str, model_name: str, timeout: float = 60.0):
        self.url = base_url.rstrip("/") + "/v1/embeddings"
        self.model_name = model_name
        self.timeout = timeout
        self.session = _session()

    @cached_property
    def tokenizer(self):
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(self.model_name)

    def tokenize(self, text: str) -> list[int]:
        # Resume sections and JDs are deliberately tokenized before they are
        # divided into model-sized inputs. Disable the tokenizer's premature
        # length warning; the actual requests are checked below.
        return self.tokenizer.encode(text, add_special_tokens=False, verbose=False)

    def decode(self, token_ids: list[int]) -> str:
        return self.tokenizer.decode(token_ids, skip_special_tokens=True)

    def encode(self, texts: Sequence[str], query: bool = False) -> np.ndarray:
        prefix = "Represent this sentence for searching relevant passages: " if query else ""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        checked: list[str] = []
        owners: list[int] = []
        prefix_tokens = len(self.tokenize(prefix)) if query else 0
        query_room = self.max_tokens - 2 - prefix_tokens
        if query and query_room <= 0:
            raise ValueError("embedding query instruction exceeds the model token limit")
        for owner, text in enumerate(texts):
            tokens = self.tokenize(text)
            if query and len(tokens) > query_room:
                pieces = [tokens[start:start + query_room]
                          for start in range(0, len(tokens), query_room)]
                logger.info("embedding query spans %s model-sized pieces", len(pieces))
                values = [prefix + self.decode(piece) for piece in pieces]
            else:
                values = [prefix + text]
            for value in values:
                if len(self.tokenize(value)) + 2 > self.max_tokens:
                    raise ValueError("embedding input exceeds the hosted model's 512-token limit")
                checked.append(value)
                owners.append(owner)
        batches = []
        for start in range(0, len(checked), 64):
            batch = checked[start : start + 64]
            response = self.session.post(
                self.url, json={"model": self.model_name, "input": batch}, timeout=self.timeout
            )
            response.raise_for_status()
            rows = response.json().get("data", [])
            if len(rows) != len(batch):
                raise ValueError("embedding service returned an incomplete batch")
            indexed = {row["index"]: row["embedding"] for row in rows}
            if set(indexed) != set(range(len(batch))):
                raise ValueError("embedding service returned invalid indexes")
            vectors = np.asarray([indexed[index] for index in range(len(batch))], dtype=np.float32)
            if vectors.shape != (len(batch), self.dimension) or not np.isfinite(vectors).all():
                raise ValueError("embedding service returned invalid vectors")
            batches.append(vectors)
        vectors = np.concatenate(batches)
        if not query:
            return vectors
        # Cosine search ignores vector magnitude. Averaging piece vectors keeps
        # evidence from the whole JD instead of silently dropping its tail.
        combined = np.zeros((len(texts), self.dimension), dtype=np.float32)
        counts = np.zeros(len(texts), dtype=np.int32)
        for owner, vector in zip(owners, vectors, strict=True):
            combined[owner] += vector
            counts[owner] += 1
        combined /= counts[:, None]
        if not np.isfinite(combined).all() or np.any(np.linalg.norm(combined, axis=1) == 0):
            raise ValueError("embedding service returned an unusable query vector")
        return combined


class HostedReranker:
    def __init__(self, base_url: str, model_name: str, timeout: float = 60.0):
        self.url = base_url.rstrip("/") + "/v1/rerank"
        self.model_name = model_name
        self.timeout = timeout
        self.session = _session()

    def score(self, jd: str, documents: Sequence[str]) -> np.ndarray:
        """Return logits so the scoring policy restores relevance with one sigmoid."""
        scores = []
        for start in range(0, len(documents), 32):
            batch = list(documents[start : start + 32])
            response = self.session.post(
                self.url,
                json={"model": self.model_name, "query": jd, "documents": batch},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
            if len(rows) != len(batch):
                raise ValueError("reranker returned an incomplete batch")
            indexed = {row["index"]: row["relevance_score"] for row in rows}
            if set(indexed) != set(range(len(batch))):
                raise ValueError("reranker returned invalid indexes")
            for index in range(len(batch)):
                probability = float(indexed[index])
                if not isfinite(probability) or not 0 <= probability <= 1:
                    raise ValueError("reranker returned an invalid relevance score")
                probability = max(1e-12, min(1 - 1e-12, probability))
                scores.append(log(probability / (1 - probability)))
        return np.asarray(scores)
