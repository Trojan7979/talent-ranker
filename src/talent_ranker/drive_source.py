"""Google Drive file and folder links as a resume source."""

from pathlib import Path

from .config import SETTINGS
from .drive_links import drive_id
from .storage import DriveFile, GoogleDriveStore


class DriveResumeSource:
    def __init__(self, store: GoogleDriveStore):
        self.store = store

    def list_resumes(self, location: str) -> list[DriveFile]:
        if "/file/d/" in location:
            file_id = drive_id(location, "file")
            item = self.store.get_resume(file_id)
            return [item]
        return self.store.list_resumes(drive_id(location, "folder"))

    def download(self, object_id: str, destination: Path) -> None:
        self.store.download(object_id, destination)

    def source_uri(self, object_id: str) -> str:
        return self.store.source_uri(object_id)

    def get_file(self, source_uri: str) -> DriveFile:
        if not source_uri.startswith("gdrive://"):
            raise ValueError("expected a Google Drive source")
        return self.store.get_resume(source_uri.removeprefix("gdrive://"))


def configured_drive_source(interactive: bool = True, token_file: Path | None = None) -> DriveResumeSource:
    return DriveResumeSource(GoogleDriveStore(
        Path(SETTINGS.google_credentials_file), token_file or Path(SETTINGS.google_token_file), interactive,
    ))
