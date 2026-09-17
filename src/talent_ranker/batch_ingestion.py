from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .identifiers import validate_candidate_id
from .storage import DriveFile, GoogleDriveStore


class ResumePipeline(Protocol):
    def ingest_pdf(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ManifestEntry:
    candidate_id: str
    drive_file_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchReport:
    discovered: int
    requested: int
    indexed: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)


def write_drive_inventory(files: list[DriveFile], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id",
        "drive_file_id",
        "file_name",
        "modified_time",
        "md5_checksum",
        "size_bytes",
        "metadata_json",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in files:
            writer.writerow(
                {
                    "candidate_id": "",
                    "drive_file_id": item.file_id,
                    "file_name": item.name,
                    "modified_time": item.modified_time,
                    "md5_checksum": item.md5_checksum,
                    "size_bytes": item.size or "",
                    "metadata_json": "",
                }
            )


def read_manifest(path: Path) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    candidate_ids: set[str] = set()
    file_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"candidate_id", "drive_file_id"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("manifest requires candidate_id and drive_file_id columns")
        for row_number, row in enumerate(reader, 2):
            raw_candidate_id = (row.get("candidate_id") or "").strip()
            file_id = (row.get("drive_file_id") or "").strip()
            if not raw_candidate_id:
                continue
            candidate_id = validate_candidate_id(raw_candidate_id)
            if not file_id:
                raise ValueError(f"manifest row {row_number} has no drive_file_id")
            if candidate_id in candidate_ids:
                raise ValueError(f"manifest has duplicate candidate ID {candidate_id}")
            if file_id in file_ids:
                raise ValueError(f"manifest has duplicate Drive file ID {file_id}")
            metadata_text = (row.get("metadata_json") or "").strip()
            try:
                metadata = json.loads(metadata_text) if metadata_text else {}
            except json.JSONDecodeError as error:
                raise ValueError(f"manifest row {row_number} has invalid metadata_json") from error
            if not isinstance(metadata, dict):
                raise TypeError(f"manifest row {row_number} metadata_json must be an object")
            entries.append(ManifestEntry(candidate_id, file_id, metadata))
            candidate_ids.add(candidate_id)
            file_ids.add(file_id)
    return entries


def ingest_drive_folder(
    pipeline: ResumePipeline,
    store: GoogleDriveStore,
    folder_id: str,
    manifest_path: Path,
    progress: Callable[[str], None] | None = None,
) -> BatchReport:
    files = store.list_pdfs(folder_id)
    inventory = {item.file_id: item for item in files}
    entries = read_manifest(manifest_path)
    mapped_file_ids = {entry.drive_file_id for entry in entries} & inventory.keys()
    report = BatchReport(len(files), len(entries), skipped=len(files) - len(mapped_file_ids))
    progress = progress or (lambda _: None)
    with tempfile.TemporaryDirectory(prefix="talent-ranker-batch-") as directory:
        for position, entry in enumerate(entries, 1):
            item = inventory.get(entry.drive_file_id)
            if item is None:
                report.failures.append(
                    f"{entry.candidate_id}: Drive file is not a PDF in the selected folder"
                )
                progress(f"[{position}/{len(entries)}] failed {entry.candidate_id}")
                continue
            try:
                local = Path(directory) / f"{entry.candidate_id}.pdf"
                store.download(item.file_id, local)
                metadata = {
                    **entry.metadata,
                    "source_file_name": item.name,
                    "source_modified_time": item.modified_time,
                    "source_md5_checksum": item.md5_checksum,
                }
                pipeline.ingest_pdf(
                    entry.candidate_id,
                    local,
                    f"gdrive://{item.file_id}",
                    metadata,
                )
                report.indexed += 1
                progress(f"[{position}/{len(entries)}] indexed {entry.candidate_id}")
            except Exception as error: # noqa: BLE001 - isolate individual file failures
                report.failures.append(f"{entry.candidate_id}: {error}")
                progress(f"[{position}/{len(entries)}] failed {entry.candidate_id}")
    return report