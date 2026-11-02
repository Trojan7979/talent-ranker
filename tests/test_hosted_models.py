from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from talent_ranker.config import Settings
from talent_ranker.access import RecruiterScope
from talent_ranker.embeddings import HostedEmbeddingEncoder, HostedReranker
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.ranking import sigmoid


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.body


class FakeTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool, verbose: bool = True) -> list[int]:
        return list(range(len(text.split())))


class WordTokenizer:
    def __init__(self):
        self.words: dict[str, int] = {}
        self.reverse: dict[int, str] = {}

    def encode(self, text: str, *, add_special_tokens: bool, verbose: bool = True) -> list[int]:
        assert verbose is False
        result = []
        for word in text.split():
            if word not in self.words:
                index = len(self.words) + 1
                self.words[word] = index
                self.reverse[index] = word
            result.append(self.words[word])
        return result

    def decode(self, token_ids, *, skip_special_tokens: bool) -> str:
        return " ".join(self.reverse[index] for index in token_ids)


def test_pipeline_requires_explicit_hosted_model_endpoints():
    settings = Settings(_env_file=None, hosted_embedding_url="", hosted_reranker_url="")
    with pytest.raises(ValueError, match="TALENT_RANKER_HOSTED_EMBEDDING_URL"):
        RankingPipeline(settings)


def test_resume_without_extractable_text_is_not_stored(monkeypatch, tmp_path):
    import talent_ranker.pipeline as pipeline_module

    path = tmp_path / "blank.pdf"
    path.write_bytes(b"blank")
    pipeline = object.__new__(RankingPipeline)
    pipeline.encoder = SimpleNamespace(tokenize=lambda text: [], decode=lambda ids: "")
    pipeline.repo = SimpleNamespace(upsert_candidate=lambda *args, **kwargs: pytest.fail("stored blank resume"))
    monkeypatch.setattr(pipeline_module, "extract_resume_document",
                        lambda path: SimpleNamespace(text="", links=[]))

    with pytest.raises(ValueError, match="no extractable text"):
        pipeline.ingest_resume("CAND_0001", path)


def test_unchanged_owned_resume_reuses_stored_embeddings(monkeypatch, tmp_path):
    import talent_ranker.pipeline as pipeline_module

    path = tmp_path / "resume.pdf"
    path.write_bytes(b"existing resume bytes")
    pipeline = object.__new__(RankingPipeline)
    pipeline.repo = SimpleNamespace(has_current_embedding=lambda *args: True)
    monkeypatch.setattr(pipeline_module, "extract_resume_document",
                        lambda path: pytest.fail("unchanged resume was extracted again"))
    scope = RecruiterScope("workspace", "recruiter", frozenset())

    pipeline.ingest_resume("CAND_0001", path, "gdrive://file", scope=scope)


def test_stale_candidate_mapping_is_rejected_before_embedding(monkeypatch, tmp_path):
    import talent_ranker.pipeline as pipeline_module

    path = tmp_path / "resume.pdf"
    path.write_bytes(b"already indexed elsewhere")
    pipeline = object.__new__(RankingPipeline)
    def reject(*args):
        raise ValueError("resume was already indexed under another candidate")
    pipeline.repo = SimpleNamespace(has_current_embedding=lambda *args: False,
                                    assert_resume_available=reject)
    monkeypatch.setattr(pipeline_module, "extract_resume_document",
                        lambda path: pytest.fail("duplicate resume reached extraction"))

    with pytest.raises(ValueError, match="another candidate"):
        pipeline.ingest_resume("CAND_0002", path, "gdrive://file",
                               scope=RecruiterScope("workspace", "recruiter", frozenset()))


def test_hosted_embedding_restores_input_order_and_checks_dimension(monkeypatch):
    encoder = HostedEmbeddingEncoder("http://models", "embedding")
    encoder.__dict__["tokenizer"] = FakeTokenizer()
    seen = []

    def post(url, *, json, timeout):
        seen.append((url, json, timeout))
        return FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.0] * 1023 + [1.0]},
                    {"index": 0, "embedding": [1.0] + [0.0] * 1023},
                ]
            }
        )

    monkeypatch.setattr(encoder.session, "post", post)
    vectors = encoder.encode(["first passage", "second passage"])
    assert vectors.shape == (2, 1024)
    assert vectors[0, 0] == 1 and vectors[1, -1] == 1
    assert seen[0][1]["input"] == ["first passage", "second passage"]


def test_hosted_embedding_adds_instruction_only_to_queries(monkeypatch):
    encoder = HostedEmbeddingEncoder("http://models", "embedding")
    encoder.__dict__["tokenizer"] = FakeTokenizer()
    requests = []

    def post(url, *, json, timeout):
        requests.append(json["input"][0])
        return FakeResponse({"data": [{"index": 0, "embedding": [1.0] * 1024}]})

    monkeypatch.setattr(encoder.session, "post", post)
    encoder.encode(["Python engineer"], query=True)
    encoder.encode(["Python engineer"])
    assert requests[0].startswith("Represent this sentence for searching relevant passages: ")
    assert requests[1] == "Python engineer"


def test_long_embedding_query_covers_tail_without_exceeding_model_limit(monkeypatch):
    encoder = HostedEmbeddingEncoder("http://models", "embedding")
    tokenizer = WordTokenizer()
    encoder.__dict__["tokenizer"] = tokenizer
    requests = []

    def post(url, *, json, timeout):
        inputs = json["input"]
        requests.extend(inputs)
        rows = []
        for index, value in enumerate(inputs):
            embedding = [0.0] * 1024
            embedding[1 if "last-requirement" in value else 0] = 1.0
            rows.append({"index": index, "embedding": embedding})
        return FakeResponse({"data": rows})

    monkeypatch.setattr(encoder.session, "post", post)
    long_jd = " ".join([f"term-{index}" for index in range(1291)] + ["last-requirement"])
    result = encoder.encode([long_jd], query=True)

    assert len(requests) == 3
    assert all(len(tokenizer.encode(value, add_special_tokens=False, verbose=False)) + 2 <= 512
               for value in requests)
    assert requests[-1].endswith("last-requirement")
    assert result.shape == (1, 1024)
    assert result[0, 1] > 0


def test_hosted_embedding_rejects_malformed_vectors(monkeypatch):
    encoder = HostedEmbeddingEncoder("http://models", "embedding")
    encoder.__dict__["tokenizer"] = FakeTokenizer()
    monkeypatch.setattr(
        encoder.session,
        "post",
        lambda *a, **k: FakeResponse({"data": [{"index": 0, "embedding": [1.0] * 384}]}),
    )
    with pytest.raises(ValueError, match="invalid vectors"):
        encoder.encode(["passage"])


def test_hosted_reranker_restores_order_without_double_sigmoid(monkeypatch):
    reranker = HostedReranker("http://models", "reranker")
    monkeypatch.setattr(
        reranker.session,
        "post",
        lambda *a, **k: FakeResponse(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.1},
                    {"index": 0, "relevance_score": 0.9},
                ]
            }
        ),
    )
    logits = reranker.score("Python role", ["Python APIs", "Retail work"])
    assert np.allclose([sigmoid(value) for value in logits], [0.9, 0.1])
    assert math.isfinite(logits[0])
