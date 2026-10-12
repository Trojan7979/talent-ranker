"""SharePoint document references shared by listing and on-demand source lookup."""

from urllib.parse import urlparse

from .storage import DriveFile


def parse_source_uri(source_uri: str) -> tuple[str, str]:
    parsed = urlparse(source_uri)
    item_id = parsed.path.removeprefix("/")
    if (parsed.scheme != "sharepoint" or not parsed.netloc or not item_id
            or "/" in item_id or parsed.query or parsed.fragment
            or parsed.username or parsed.password or ":" in parsed.netloc):
        raise ValueError("Invalid SharePoint source reference")
    # Drive IDs are case-sensitive; urlparse.hostname would lowercase them.
    return parsed.netloc, item_id


def sharepoint_file(item: dict) -> DriveFile:
    web_url = item.get("webUrl", "")
    if web_url:
        parsed = urlparse(web_url)
        if (parsed.scheme != "https"
                or not (parsed.hostname or "").endswith(".sharepoint.com")
                or parsed.username or parsed.password or parsed.port
                or "\\" in web_url or any(ord(char) < 32 for char in web_url)):
            raise ValueError("SharePoint returned an invalid document link")
    return DriveFile(
        file_id=item["id"], name=item["name"],
        modified_time=item.get("lastModifiedDateTime", ""), size=item.get("size"),
        web_url=web_url, etag=item.get("eTag", ""),
    )
