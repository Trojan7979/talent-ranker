from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .identifiers import validate_candidate_id

DRIVE_READONLY_SCOPE = ["https://www.googleapis.com/auth/drive.readonly"]


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    modified_time: str = ""
    md5_checksum: str = ""
    size: int | None = None


class ClientStorageAdapter(Protocol):
    """A read-only adapter for storage controlled by a client."""

    def download(self, object_id: str, destination: Path) -> None: ...

    def source_uri(self, object_id: str) -> str: ...


class CanonicalObjectStore(Protocol):
    """Durable storage used as the source of truth by the ranking platform."""

    def put_file(self, object_key: str, source: Path, content_type: str) -> str: ...


class S3ObjectStore:
    """Canonical object storage backed by S3 or an S3-compatible service."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "talent-ranker",
        endpoint_url: str | None = None,
        client=None,
    ):
        if not bucket:
            raise ValueError("canonical S3 bucket must be configured")
        if client is None:
            import boto3

            client = boto3.client("s3", endpoint_url=endpoint_url)
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client

    def put_file(self, object_key: str, source: Path, content_type: str) -> str:
        key = "/".join(part for part in (self.prefix, object_key.lstrip("/")) if part)
        self.client.upload_file(
            str(source),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"s3://{self.bucket}/{key}"


class FilesystemObjectStore:
    """Local canonical store for development and tests."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def put_file(self, object_key: str, source: Path, content_type: str) -> str:
        del content_type
        destination = (self.root / object_key).resolve()
        if self.root not in destination.parents:
            raise ValueError("object key escapes canonical storage root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return destination.as_uri()


def store_canonical_resume(
    store: CanonicalObjectStore,
    candidate_id: str,
    source: Path,
) -> str:
    """Store an immutable, content-addressed resume and return its canonical URI."""
    candidate_id = validate_candidate_id(candidate_id)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    suffix = source.suffix.lower() or ".pdf"
    key = f"candidates/{candidate_id}/{digest}{suffix}"
    return store.put_file(key, source, "application/pdf")


class GoogleDriveStore:
    """Downloads private PDF blobs from a user-authorized Google Drive account."""

    def __init__(self, credentials_file: Path, token_file: Path):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.client = self._build_client()

    def download(self, file_id: str, destination: Path) -> None:
        from googleapiclient.http import MediaIoBaseDownload

        destination.parent.mkdir(parents=True, exist_ok=True)
        request = self.client.files().get_media(fileId=file_id)
        with destination.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)

    def source_uri(self, file_id: str) -> str:
        return f"gdrive://{file_id}"

    def list_pdfs(self, folder_id: str) -> list[DriveFile]:
        escaped_folder_id = folder_id.replace("'", "\\'")
        query = (
            f"'{escaped_folder_id}' in parents and trashed = false and mimeType = 'application/pdf'"
        )
        files: list[DriveFile] = []
        page_token = None
        while True:
            response = (
                self.client.files()
                .list(
                    q=query,
                    fields="nextPageToken,files(id,name,modifiedTime,md5Checksum,size)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute(num_retries=3)
            )
            files.extend(
                DriveFile(
                    file_id=item["id"],
                    name=item["name"],
                    modified_time=item.get("modifiedTime", ""),
                    md5_checksum=item.get("md5Checksum", ""),
                    size=int(item["size"]) if item.get("size") else None,
                )
                for item in response.get("files", [])
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                return sorted(files, key=lambda item: (item.name.lower(), item.file_id))

    def _build_client(self):
        from googleapiclient.discovery import build

        credentials = self._credentials()
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.credentials_file.is_file():
            raise FileNotFoundError(
                f"Google OAuth client file not found: {self.credentials_file.resolve()}"
            )
        credentials = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_file), DRIVE_READONLY_SCOPE
            )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_file), DRIVE_READONLY_SCOPE
            )
            credentials = flow.run_local_server(port=0)
        self._save_token(credentials)
        return credentials

    def _save_token(self, credentials) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
