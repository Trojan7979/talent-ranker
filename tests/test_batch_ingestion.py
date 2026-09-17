from pathlib import Path

from talent_ranker.batch_ingestion import (
    ingest_drive_folder,
    read_manifest,
    write_drive_inventory,
)
from talent_ranker.storage import DriveFile


class FakeDriveStore:
    def __init__(self, files: list[DriveFile]):
        self.files = files

    def list_pdfs(self, folder_id: str) -> list[DriveFile]:
        assert folder_id == "folder-1"
        return self.files

    def download(self, file_id: str, destination: Path) -> None:
        destination.write_bytes(f"PDF {file_id}".encode())


class FakePipeline:
    def __init__(self):
        self.calls: list[tuple] = []

    def ingest_pdf(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.calls.append((candidate_id, path.read_bytes(), source_uri, metadata))


def test_inventory_round_trip_and_batch_ingestion(tmp_path: Path):
    files = [
        DriveFile("file-1", "resume-one.pdf", "2026-09-17T10:00:00Z", "checksum", 123),
        DriveFile("file-2", "resume-two.pdf"),
    ]
    manifest = tmp_path / "manifest.csv"
    write_drive_inventory(files, manifest)
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace(",file-1,", "CAND_0001,file-1,"), encoding="utf-8")

    entries = read_manifest(manifest)
    assert [entry.candidate_id for entry in entries] == ["CAND_0001"]

    pipeline = FakePipeline()
    report = ingest_drive_folder(pipeline, FakeDriveStore(files), "folder-1", manifest)
    assert report.indexed == 1
    assert report.skipped == 1
    assert not report.failures
    assert pipeline.calls[0][2] == "gdrive://file-1"
    assert pipeline.calls[0][3]["source_file_name"] == "resume-one.pdf"


def test_manifest_rejects_duplicate_candidate_ids(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "candidate_id,drive_file_id\nCAND_0001,file-1\nCAND_0001,file-2\n",
        encoding="utf-8",
    )
    try:
        read_manifest(manifest)
    except ValueError as error:
        assert "duplicate candidate ID" in str(error)
    else:
        raise AssertionError("duplicate candidate ID was accepted")
