from pathlib import Path
from types import SimpleNamespace

import pytest

from talent_ranker.batch_ingestion import ManifestEntry, ingest_source_entries
from talent_ranker.storage import DriveFile


@pytest.mark.parametrize("fail_first", [False, True])
def test_batch_keeps_source_metadata_and_cleans_each_file_before_next_download(fail_first):
    paths = []
    calls = []

    class Source:
        def list_resumes(self, folder):
            return [DriveFile(
                key, f"{key}.pdf", web_url=f"https://client.sharepoint.com/{key}.pdf",
                etag=f"etag-{key}",
            ) for key in ("one", "two")]

        def source_uri(self, object_id):
            return f"sharepoint://drive/{object_id}"

        def download(self, object_id, destination):
            assert all(not path.exists() for path in paths)
            paths.append(destination)
            destination.write_bytes(object_id.encode())

    class Pipeline:
        def ingest_resume(self, candidate_id, path, source_uri, metadata):
            assert path.is_file()
            if fail_first and candidate_id == "CAND_0001":
                raise ValueError("cannot extract this document")
            calls.append((source_uri, metadata))

    report = ingest_source_entries(
        Pipeline(), Source(), "folder",
        [ManifestEntry("CAND_0001", "one"), ManifestEntry("CAND_0002", "two")],
        "SharePoint",
    )
    assert report.indexed == (1 if fail_first else 2)
    assert len(report.failures) == int(fail_first)
    assert all(not path.exists() for path in paths)
    uri, metadata = calls[-1]
    assert uri == metadata["client_source_uri"] == "sharepoint://drive/two"
    assert metadata["source_web_url"] == "https://client.sharepoint.com/two.pdf"
    assert metadata["source_etag"] == "etag-two"


def test_sharepoint_cli_uses_client_source_without_configuring_copy_storage(monkeypatch):
    from talent_ranker import cli

    closed = []
    pipeline = SimpleNamespace(repo=SimpleNamespace(close=lambda: closed.append(True)))
    source = object()
    monkeypatch.setattr(cli, "RankingPipeline", lambda _: pipeline)
    monkeypatch.setattr(cli, "sharepoint_store", lambda: source)
    monkeypatch.setattr(cli, "cli_scope", lambda _: SimpleNamespace(actor_id="recruiter"))

    def forbidden_copy():
        pytest.fail("SharePoint must not initialize canonical storage")

    def ingest(actual_pipeline, actual_source, folder_url, manifest, progress, scope):
        assert (actual_pipeline, actual_source) == (pipeline, source)
        assert folder_url == "folder" and manifest == Path("manifest.csv")
        assert scope.actor_id == "recruiter"
        return SimpleNamespace(indexed=1, skipped=0, failures=[])

    monkeypatch.setattr(cli, "canonical_store", forbidden_copy)
    monkeypatch.setattr(cli, "ingest_sharepoint_folder", ingest)
    cli.run_pipeline_command(SimpleNamespace(
        command="ingest-sharepoint-folder", folder_url="folder", manifest=Path("manifest.csv"),
    ))
    assert closed == [True]
