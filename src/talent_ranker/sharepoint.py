"""Read-only SharePoint document-library access through Microsoft Graph."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .sharepoint_documents import parse_source_uri, sharepoint_file
from .storage import DriveFile

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
MAX_RESUME_BYTES = 50 * 1024 * 1024

@dataclass(frozen=True)
class FolderLink:
    hostname: str
    site_path: str
    folder_path: str

    @classmethod
    def parse(cls, link: str) -> FolderLink:
        parsed = urlparse(link.strip())
        hostname = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not hostname.endswith(".sharepoint.com")
                or parsed.username or parsed.password or parsed.port or parsed.fragment):
            raise ValueError("Provide an HTTPS SharePoint folder URL")
        path = unquote(parsed.path)
        if path.lower().endswith("/forms/allitems.aspx"):
            path = unquote(parse_qs(parsed.query).get("id", [""])[0])
        elif path.startswith("/:f:/r/"):
            path = path[len("/:f:/r"):]
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[0].lower() not in {"sites", "teams"}:
            raise ValueError("SharePoint URL must identify a folder in a site document library")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("SharePoint folder path is invalid")
        return cls(hostname, "/" + "/".join(parts[:2]), "/" + "/".join(parts))


def _graph_url(path: str) -> str:
    return GRAPH_ROOT + path


class ClientCredentials:
    """Keep a short-lived Graph token in memory; never expose it to the browser."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, session: requests.Session):
        if not all((tenant_id, client_id, client_secret)):
            raise ValueError("SharePoint tenant, client ID, and client secret must be configured")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session
        self._token = ""
        self._expires_at = 0.0

    def token(self) -> str:
        if time.monotonic() < self._expires_at:
            return self._token
        response = self.session.post(
            f"https://login.microsoftonline.com/{quote(self.tenant_id, safe='')}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._expires_at = time.monotonic() + max(0, int(payload["expires_in"]) - 60)
        return self._token


class SharePointFolderSource:
    """Resolve one authorized folder, enumerate resumes, and download by stable item ID."""

    def __init__(self, credentials: ClientCredentials, session: requests.Session | None = None):
        self.credentials = credentials
        self.session = session or requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://graph.microsoft.com/", HTTPAdapter(max_retries=retry))
        self.drive_id: str | None = None

    def _get(self, url: str, *, stream: bool = False, redirects: bool = True):
        if not url.startswith(GRAPH_ROOT + "/"):
            raise ValueError("Graph response contained an unexpected URL")
        response = self.session.get(
            url, headers={"Authorization": f"Bearer {self.credentials.token()}"},
            timeout=30, stream=stream, allow_redirects=redirects,
        )
        response.raise_for_status()
        return response

    def _pages(self, url: str):
        while url:
            payload = self._get(url).json()
            yield from payload.get("value", [])
            url = payload.get("@odata.nextLink")

    def resolve(self, folder_url: str) -> tuple[str, str]:
        link = FolderLink.parse(folder_url)
        site_path = quote(link.site_path, safe="/")
        site = self._get(_graph_url(f"/sites/{link.hostname}:{site_path}")).json()
        site_id = quote(site["id"], safe="")
        drives = self._pages(_graph_url(f"/sites/{site_id}/drives"))
        folder_path = link.folder_path.casefold().rstrip("/")
        drive = None
        for item in drives:
            library_url = urlparse(item.get("webUrl", ""))
            library_path = unquote(library_url.path).casefold().rstrip("/")
            if ((library_url.hostname or "").lower() == link.hostname
                    and (folder_path == library_path
                         or folder_path.startswith(library_path + "/"))):
                drive = item
                break
        if drive is None:
            raise ValueError("SharePoint folder is not in an accessible document library")
        drive_id = drive["id"]
        library_path = unquote(urlparse(drive["webUrl"]).path).rstrip("/")
        relative = link.folder_path[len(library_path):].strip("/")
        base = f"/drives/{quote(drive_id, safe='')}"
        endpoint = f"{base}/root:/{quote(relative, safe='/')}" if relative else f"{base}/root"
        folder = self._get(_graph_url(endpoint)).json()
        if "folder" not in folder:
            raise ValueError("SharePoint URL does not point to a folder")
        self.drive_id = drive_id
        return drive_id, folder["id"]

    def list_resumes(self, folder_url: str) -> list[DriveFile]:
        drive_id, root_id = self.resolve(folder_url)
        queue = deque([root_id])
        files: list[DriveFile] = []
        while queue:
            folder_id = queue.popleft()
            endpoint = _graph_url(
                f"/drives/{quote(drive_id, safe='')}/items/{quote(folder_id, safe='')}/children"
            )
            for item in self._pages(endpoint):
                if "folder" in item:
                    queue.append(item["id"])
                elif "file" in item and item.get("name", "").lower().endswith(
                    (".pdf", ".docx")
                ):
                    files.append(sharepoint_file(item))
        return files

    def get_file(self, source_uri: str) -> DriveFile:
        """Resolve the current browser link by stable ID without downloading the document."""
        drive_id, item_id = parse_source_uri(source_uri)
        endpoint = _graph_url(
            f"/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"
            "?$select=id,name,webUrl,eTag,lastModifiedDateTime,size,file,deleted"
        )
        item = self._get(endpoint).json()
        if "file" not in item or "deleted" in item:
            raise ValueError("SharePoint source is no longer a file")
        return sharepoint_file(item)

    def list_pdfs(self, folder_url: str) -> list[DriveFile]:
        """Compatibility alias; the source now includes DOCX resumes."""
        return self.list_resumes(folder_url)

    def download(self, object_id: str, destination: Path) -> None:
        if not self.drive_id:
            raise RuntimeError("resolve the SharePoint folder before downloading")
        endpoint = _graph_url(
            f"/drives/{quote(self.drive_id, safe='')}/items/{quote(object_id, safe='')}/content"
        )
        response = self._get(endpoint, stream=True, redirects=False)
        if response.status_code != 302:
            raise ValueError("SharePoint did not provide a download URL")
        download_url = response.headers.get("Location", "")
        if urlparse(download_url).scheme != "https":
            raise ValueError("SharePoint returned an invalid download URL")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with self.session.get(download_url, timeout=60, stream=True) as download:
                download.raise_for_status()
                if int(download.headers.get("Content-Length", "0")) > MAX_RESUME_BYTES:
                    raise ValueError("resume exceeds the 50 MB limit")
                size = 0
                with temporary.open("wb") as handle:
                    for chunk in download.iter_content(chunk_size=256 * 1024):
                        size += len(chunk)
                        if size > MAX_RESUME_BYTES:
                            raise ValueError("resume exceeds the 50 MB limit")
                        handle.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def source_uri(self, object_id: str) -> str:
        if not self.drive_id:
            raise RuntimeError("resolve the SharePoint folder before reading its source URI")
        return f"sharepoint://{self.drive_id}/{object_id}"


def configured_sharepoint_source(settings) -> SharePointFolderSource:
    session = requests.Session()
    credentials = ClientCredentials(
        settings.sharepoint_tenant_id,
        settings.sharepoint_client_id,
        settings.sharepoint_client_secret.get_secret_value()
        if settings.sharepoint_client_secret else "",
        session,
    )
    return SharePointFolderSource(credentials, session)
