from pathlib import Path

from talent_ranker.storage import FilesystemObjectStore, S3ObjectStore, store_canonical_resume


class FakeS3Client:
    def __init__(self):
        self.uploads: list[tuple] = []

    def upload_file(self, source, bucket, key, ExtraArgs):
        self.uploads.append((source, bucket, key, ExtraArgs))


def test_resume_is_stored_under_content_addressed_canonical_key(tmp_path: Path):
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    store = FilesystemObjectStore(tmp_path / "canonical")

    uri = store_canonical_resume(store, "CAND_0001", source)

    assert uri.startswith("file:")
    stored = list((tmp_path / "canonical" / "candidates" / "CAND_0001").glob("*.pdf"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"resume"


def test_s3_store_returns_canonical_uri(tmp_path: Path):
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    client = FakeS3Client()
    store = S3ObjectStore("resume-bucket", "tenant-a", client=client)

    uri = store.put_file("candidates/CAND_0001/file.pdf", source, "application/pdf")

    assert uri == "s3://resume-bucket/tenant-a/candidates/CAND_0001/file.pdf"
    assert client.uploads[0][2] == "tenant-a/candidates/CAND_0001/file.pdf"
    assert client.uploads[0][3] == {"ContentType": "application/pdf"}
