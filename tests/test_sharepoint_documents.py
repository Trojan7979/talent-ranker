import pytest

from talent_ranker.sharepoint import SharePointFolderSource
from talent_ranker.sharepoint_documents import parse_source_uri, sharepoint_file


def test_stable_source_reference_preserves_case():
    assert parse_source_uri("sharepoint://DriveABC/ItemXYZ") == ("DriveABC", "ItemXYZ")


@pytest.mark.parametrize("uri", [
    "https://client.sharepoint.com/resume.pdf", "sharepoint:///item", "sharepoint://drive/",
    "sharepoint://drive/item/extra", "sharepoint://drive/item?token=secret",
    "sharepoint://user@drive/item", "sharepoint://drive:443/item",
])
def test_invalid_source_references_are_rejected(uri):
    with pytest.raises(ValueError):
        parse_source_uri(uri)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://evil.test/resume.pdf",
    "https://client.sharepoint.com.evil.test/resume.pdf",
    "http://client.sharepoint.com/resume.pdf", "https://user@client.sharepoint.com/resume.pdf",
    "https://client.sharepoint.com:8443/resume.pdf",
    "https://evil.test\\@client.sharepoint.com/resume.pdf",
])
def test_only_normal_sharepoint_browser_links_are_exposed(url):
    with pytest.raises(ValueError):
        sharepoint_file({"id": "item", "name": "resume.pdf", "webUrl": url})


def test_lookup_uses_graph_metadata_by_id_without_downloading_file():
    source = object.__new__(SharePointFolderSource)
    urls = []

    def get(url):
        urls.append(url)

        class Response:
            def json(self):
                return {
                    "id": "ItemXYZ", "name": "renamed.docx", "file": {}, "eTag": "new-tag",
                    "webUrl": "https://client.sharepoint.com/renamed.docx",
                    "@microsoft.graph.downloadUrl": "https://private.test/secret-token",
                }

        return Response()

    source._get = get
    file = source.get_file("sharepoint://DriveABC/ItemXYZ")
    assert file.name == "renamed.docx" and file.etag == "new-tag"
    assert file.web_url == "https://client.sharepoint.com/renamed.docx"
    assert len(urls) == 1
    assert urls[0].startswith("https://graph.microsoft.com/v1.0/drives/DriveABC/items/ItemXYZ?")
    assert "/content" not in urls[0]
