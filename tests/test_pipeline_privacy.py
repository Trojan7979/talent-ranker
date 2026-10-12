from pathlib import Path

from talent_ranker.documents import ExtractedResume
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.resume_links import extract_links


class StubEncoder:
    @staticmethod
    def tokenize(text: str) -> list[str]:
        return text.split()

    @staticmethod
    def decode(tokens: list[str]) -> str:
        return " ".join(tokens)

    @staticmethod
    def encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]


class CapturingRepository:
    def __init__(self) -> None:
        self.raw_text = ""
        self.chunk_content: list[str] = []

    def upsert_candidate(
        self,
        candidate_id: str,
        source_uri: str,
        source_sha256: str,
        raw_text: str,
        chunks: list,
        vectors: list,
        metadata: dict | None,
        *, links=(),
    ) -> None:
        self.raw_text = raw_text
        self.chunk_content = [chunk.content for chunk in chunks]
        self.links = links


def test_ingestion_sanitizes_text_before_chunking_and_storage(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"test resume")
    extracted = (
        "SUMMARY\nCustomer support specialist\n"
        "CONTACT\nalex@example.com | +91 98765 43210\n"
        "PROJECT\ngithub.com/alex/project\n"
        "EXPERIENCE\nManaged customer onboarding and retention."
    )
    monkeypatch.setattr("talent_ranker.pipeline.extract_resume_document",
                        lambda _: ExtractedResume(extracted, extract_links(extracted)))
    pipeline = object.__new__(RankingPipeline)
    pipeline.encoder = StubEncoder()
    pipeline.repo = CapturingRepository()

    pipeline.ingest_pdf("CAND_0001", Path(resume))

    indexed_content = " ".join(pipeline.repo.chunk_content)
    assert "alex@example.com" not in pipeline.repo.raw_text
    assert "98765 43210" not in pipeline.repo.raw_text
    assert "alex@example.com" not in indexed_content
    assert "98765 43210" not in indexed_content
    assert "Managed customer onboarding and retention" in indexed_content
    assert "github.com" not in indexed_content
    assert pipeline.repo.links[0].url == "https://github.com/alex/project"
