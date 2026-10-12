from types import SimpleNamespace

import pytest
from docx import Document

from sieve_app.resume_identity import extract_identity
from talent_ranker.batch_ingestion import ManifestEntry, ingest_source_entries
from talent_ranker.documents import extract_resume
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.storage import (
    DriveFile,
    FilesystemObjectStore,
    GoogleDriveStore,
    store_canonical_resume,
)


class Encoder:
    @staticmethod
    def tokenize(text):
        return text.split()

    @staticmethod
    def decode(tokens):
        return " ".join(tokens)

    @staticmethod
    def encode(texts):
        return [[0.0] * 384 for _ in texts]


class Repository:
    def upsert_candidate(self, candidate_id, source_uri, digest, raw_text,
                         chunks, vectors, metadata, *, links=()):
        self.raw_text = raw_text
        self.chunks = chunks


def test_docx_header_and_table_are_extracted_but_contacts_are_not_indexed(tmp_path):
    path = tmp_path / "resume.docx"
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Jane Doe\njane@example.com"
    document.add_paragraph("Experienced software engineer delivering reliable services.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skills"
    table.cell(0, 1).text = "Python, PostgreSQL, distributed systems"
    document.add_paragraph("Built ingestion pipelines for recruiting operations.")
    document.save(path)

    extracted = extract_resume(path)
    assert extract_identity(extracted).email == "jane@example.com"
    assert "Python, PostgreSQL" in extracted

    pipeline = object.__new__(RankingPipeline)
    pipeline.encoder = Encoder()
    pipeline.repo = Repository()
    pipeline.ingest_resume("CAND_0001", path)
    assert "jane@example.com" not in pipeline.repo.raw_text
    assert "jane@example.com" not in " ".join(c.content for c in pipeline.repo.chunks)
    assert "distributed systems" in pipeline.repo.raw_text


def test_canonical_docx_uses_word_content_type(tmp_path):
    path = tmp_path / "resume.docx"
    path.write_bytes(b"docx fixture")

    class Store:
        def put_file(self, object_key, source, content_type):
            assert object_key.endswith(".docx")
            assert content_type == (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            return "s3://test/" + object_key

    assert store_canonical_resume(Store(), "CAND_0001", path).startswith("s3://test/")


def test_docx_source_keeps_extension_through_canonical_batch_ingestion(tmp_path):
    resume = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("Jane Doe has built reliable recruiting systems and data pipelines.")
    document.add_paragraph("Experienced with Python, PostgreSQL, and operations at scale.")
    document.save(resume)

    class Source:
        def list_resumes(self, folder):
            return [DriveFile("item-1", "jane.docx")]

        def download(self, object_id, destination):
            destination.write_bytes(resume.read_bytes())

        def source_uri(self, object_id):
            return f"sharepoint://drive/{object_id}"

    class Pipeline:
        def ingest_resume(self, candidate_id, path, source_uri, metadata):
            assert path.suffix == ".docx"
            assert "PostgreSQL" in extract_resume(path)
            assert source_uri.endswith(".docx")
            self.called = True

    pipeline = Pipeline()
    report = ingest_source_entries(
        pipeline, Source(), "folder", [ManifestEntry("CAND_0001", "item-1")],
        "SharePoint", canonical_store=FilesystemObjectStore(tmp_path / "canonical"),
    )
    assert report.indexed == 1
    assert pipeline.called


@pytest.mark.parametrize("name,mime_type", [
    ("resume.pdf", "application/pdf"),
    ("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
])
def test_drive_single_file_ingestion_preserves_resume_type(tmp_path, monkeypatch, name, mime_type):
    from talent_ranker import cli

    item = {"name": name, "mimeType": mime_type}
    request = SimpleNamespace(execute=lambda **kwargs: item)
    files = SimpleNamespace(get=lambda **kwargs: request)
    source = object.__new__(GoogleDriveStore)
    source.client = SimpleNamespace(files=lambda: files)
    source.download = lambda file_id, path: path.write_bytes(b"resume fixture")
    source.source_uri = lambda file_id: f"gdrive://{file_id}"
    calls = []
    pipeline = SimpleNamespace(
        repo=SimpleNamespace(close=lambda: None),
        ingest_resume=lambda candidate_id, path, uri, metadata: calls.append(
            (path.suffix, uri, metadata["client_source_uri"])
        ),
    )
    monkeypatch.setattr(cli, "drive_store", lambda: source)
    monkeypatch.setattr(cli, "canonical_store", lambda: FilesystemObjectStore(tmp_path))
    monkeypatch.setattr(cli, "RankingPipeline", lambda settings: pipeline)

    cli.run_pipeline_command(SimpleNamespace(
        command="ingest-drive", candidate_id="CAND_0001", file_id="file-1", metadata=None,
    ))

    assert calls[0][0] == f".{name.rsplit('.', 1)[1]}"
    assert calls[0][1].endswith(calls[0][0])
    assert calls[0][2] == "gdrive://file-1"


def test_drive_single_file_rejects_native_google_docs():
    item = {"name": "resume", "mimeType": "application/vnd.google-apps.document"}
    request = SimpleNamespace(execute=lambda **kwargs: item)
    source = object.__new__(GoogleDriveStore)
    source.client = SimpleNamespace(files=lambda: SimpleNamespace(get=lambda **kwargs: request))

    with pytest.raises(ValueError, match="PDF or DOCX"):
        source.resume_name("file-1")
