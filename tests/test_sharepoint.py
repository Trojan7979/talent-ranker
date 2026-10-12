from pathlib import Path

import pytest

from talent_ranker.batch_ingestion import ingest_sharepoint_folder
from talent_ranker.sharepoint import ClientCredentials, FolderLink, SharePointFolderSource
from talent_ranker.storage import FilesystemObjectStore

FOLDER_URL = "https://contoso.sharepoint.com/sites/Recruiting/Shared%20Documents/Resumes"
GRAPH = "https://graph.microsoft.com/v1.0"


class Response:
    def __init__(self, payload=None, *, status=200, headers=None, content=b""):
        self.payload = payload or {}
        self.status_code = status
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self.payload

    def raise_for_status(self):
        assert self.status_code < 400

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Session:
    def __init__(self):
        self.calls = []

    def mount(self, *_):
        pass

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == f"{GRAPH}/sites/contoso.sharepoint.com:/sites/Recruiting":
            return Response({"id": "site-1"})
        if url == f"{GRAPH}/sites/site-1/drives":
            return Response({"value": [{
                "id": "drive-1",
                "webUrl": "https://contoso.sharepoint.com/sites/Recruiting/Shared%20Documents",
            }]})
        if url == f"{GRAPH}/drives/drive-1/root:/Resumes":
            return Response({"id": "folder-1", "folder": {}})
        if url == f"{GRAPH}/drives/drive-1/items/folder-1/children":
            return Response({
                "value": [
                    {"id": "file-1", "name": "candidate.pdf", "file": {}, "size": 10},
                    {"id": "folder-2", "name": "More", "folder": {}},
                ],
                "@odata.nextLink": f"{GRAPH}/drives/drive-1/items/folder-1/children?$skiptoken=next",
            })
        if url.endswith("?$skiptoken=next"):
            return Response({"value": [{"id": "text-1", "name": "notes.txt", "file": {}}]})
        if url == f"{GRAPH}/drives/drive-1/items/folder-2/children":
            return Response({"value": [
                {"id": "file-2", "name": "second.PDF", "file": {}},
                {"id": "file-3", "name": "third.docx", "file": {}},
            ]})
        if url == f"{GRAPH}/drives/drive-1/items/file-1/content":
            return Response(status=302, headers={"Location": "https://download.example.test/file-1"})
        if url == "https://download.example.test/file-1":
            return Response(content=b"%PDF mock")
        raise AssertionError(url)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response({"access_token": "new-token", "expires_in": 3600})


class Credentials:
    def token(self):
        return "test-token"


def test_app_credentials_request_graph_token_once():
    session = Session()
    credentials = ClientCredentials("tenant-id", "client-id", "secret", session)
    assert credentials.token() == "new-token"
    assert credentials.token() == "new-token"
    assert len(session.calls) == 1
    assert session.calls[0][1]["data"]["scope"] == "https://graph.microsoft.com/.default"


def test_folder_link_parses_normal_and_all_items_urls():
    normal = FolderLink.parse(FOLDER_URL)
    assert normal.site_path == "/sites/Recruiting"
    assert normal.folder_path == "/sites/Recruiting/Shared Documents/Resumes"
    all_items = (
        "https://contoso.sharepoint.com/sites/Recruiting/Shared%20Documents/Forms/"
        "AllItems.aspx?id=%2Fsites%2FRecruiting%2FShared%20Documents%2FResumes"
    )
    assert FolderLink.parse(all_items) == normal
    assert FolderLink.parse(
        "https://contoso.sharepoint.com/:f:/r/sites/Recruiting/"
        "Shared%20Documents/Resumes?web=1"
    ) == normal
    with pytest.raises(ValueError):
        FolderLink.parse("http://contoso.sharepoint.com/sites/Recruiting/Docs/Resumes")


def test_sharepoint_folder_lists_paged_pdf_and_docx_and_downloads_without_token(tmp_path: Path):
    session = Session()
    source = SharePointFolderSource(Credentials(), session)
    files = source.list_resumes(FOLDER_URL)
    assert [item.file_id for item in files] == ["file-1", "file-2", "file-3"]
    assert source.source_uri("file-1") == "sharepoint://drive-1/file-1"
    target = tmp_path / "resume.pdf"
    source.download("file-1", target)
    assert target.read_bytes() == b"%PDF mock"
    assert session.calls[-1][1].get("headers") is None
    assert session.calls[-2][1]["headers"]["Authorization"] == "Bearer test-token"


class Pipeline:
    def __init__(self):
        self.calls = []

    def ingest_resume(self, candidate_id, path, source_uri, metadata):
        self.calls.append((candidate_id, path.read_bytes(), source_uri, metadata))


def test_sharepoint_manifest_feeds_existing_canonical_ingestion(tmp_path: Path):
    manifest = tmp_path / "mapped.csv"
    manifest.write_text(
        "candidate_id,sharepoint_file_id\nCAND_0001,file-1\n", encoding="utf-8"
    )
    pipeline = Pipeline()
    source = SharePointFolderSource(Credentials(), Session())
    report = ingest_sharepoint_folder(
        pipeline, source, FOLDER_URL, manifest,
        canonical_store=FilesystemObjectStore(tmp_path / "canonical"),
    )
    assert (report.discovered, report.indexed, report.skipped) == (3, 1, 2)
    assert not report.failures
    assert pipeline.calls[0][0] == "CAND_0001"
    assert pipeline.calls[0][2].startswith("file:")
    assert pipeline.calls[0][3]["client_source_uri"] == "sharepoint://drive-1/file-1"
