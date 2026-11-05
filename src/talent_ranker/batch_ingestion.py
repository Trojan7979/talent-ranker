from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .access import RecruiterScope
from .identifiers import validate_candidate_id
from .storage import CanonicalObjectStore, ClientStorageAdapter, DriveFile, store_canonical_resume


class IngestionOutcome(StrEnum):
    EMBEDDED = "embedded"
    UNCHANGED = "unchanged"


class ResumePipeline(Protocol):
    def ingest_resume(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
        scope: RecruiterScope | None = None,
    ) -> IngestionOutcome: ...


class FolderSource(ClientStorageAdapter, Protocol):
    def list_resumes(self, folder: str) -> list[DriveFile]: ...


@dataclass(frozen=True)
class ManifestEntry:
    candidate_id: str
    object_id: str
    metadata: dict = field(default_factory=dict)
    expected_sha256: str | None = None


@dataclass
class BatchReport:
    discovered: int
    requested: int
    embedded: int = 0
    unchanged: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def indexed(self) -> int:
        """Backward-compatible name for callers that have not adopted outcome terminology."""
        return self.embedded


def write_inventory(files: list[DriveFile], output: Path, id_column: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id",
        id_column,
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
                    id_column: item.file_id,
                    "file_name": item.name,
                    "modified_time": item.modified_time,
                    "md5_checksum": item.md5_checksum,
                    "size_bytes": item.size or "",
                    "metadata_json": "",
                }
            )


def write_drive_inventory(files: list[DriveFile], output: Path) -> None:
    write_inventory(files, output, "drive_file_id")


def read_manifest(path: Path, id_column: str = "drive_file_id") -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    candidate_ids: set[str] = set()
    file_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"candidate_id", id_column}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"manifest requires candidate_id and {id_column} columns")
        for row_number, row in enumerate(reader, 2):
            raw_candidate_id = (row.get("candidate_id") or "").strip()
            file_id = (row.get(id_column) or "").strip()
            if not raw_candidate_id:
                continue
            candidate_id = validate_candidate_id(raw_candidate_id)
            if not file_id:
                raise ValueError(f"manifest row {row_number} has no {id_column}")
            if candidate_id in candidate_ids:
                raise ValueError(f"manifest has duplicate candidate ID {candidate_id}")
            if file_id in file_ids:
                raise ValueError(f"manifest has duplicate {id_column} {file_id}")
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


def ingest_source_folder(
    pipeline: ResumePipeline,
    store: FolderSource,
    folder: str,
    manifest_path: Path,
    id_column: str,
    source_name: str,
    progress: Callable[[str], None] | None = None,
    canonical_store: CanonicalObjectStore | None = None,
    scope: RecruiterScope | None = None,
) -> BatchReport:
    return ingest_source_entries(
        pipeline, store, folder, read_manifest(manifest_path, id_column), source_name,
        progress, canonical_store, scope=scope,
    )


def ingest_source_entries(
    pipeline: ResumePipeline,
    store: FolderSource,
    folder: str,
    entries: list[ManifestEntry],
    source_name: str,
    progress: Callable[[str], None] | None = None,
    canonical_store: CanonicalObjectStore | None = None,
    on_result: Callable[[str, IngestionOutcome | None, str | None], None] | None = None,
    scope: RecruiterScope | None = None,
) -> BatchReport:
    files = store.list_resumes(folder)
    inventory = {item.file_id: item for item in files}
    mapped_file_ids = {entry.object_id for entry in entries} & inventory.keys()
    report = BatchReport(len(files), len(entries), skipped=len(files) - len(mapped_file_ids))
    progress = progress or (lambda _: None)
    with tempfile.TemporaryDirectory(prefix="talent-ranker-batch-") as directory:
        for position, entry in enumerate(entries, 1):
            item = inventory.get(entry.object_id)
            if item is None:
                failure = f"{entry.candidate_id}: {source_name} file is not a resume in the selected folder"
                report.failures.append(failure)
                progress(f"[{position}/{len(entries)}] failed {entry.candidate_id}")
                if on_result:
                    on_result(entry.candidate_id, None, failure)
                continue
            failure = None
            local = None
            try:
                suffix = Path(item.name).suffix.lower()
                if suffix not in {".pdf", ".docx"}:
                    raise ValueError("resume must be a PDF or DOCX file")
                local = Path(directory) / f"{entry.candidate_id}{suffix}"
                store.download(item.file_id, local)
                if entry.expected_sha256 and (
                    hashlib.sha256(local.read_bytes()).hexdigest() != entry.expected_sha256
                ):
                    raise ValueError("source resume changed since recruiter review")
                metadata = {
                    **entry.metadata,
                    "source_file_name": item.name,
                    "source_modified_time": item.modified_time,
                    "source_md5_checksum": item.md5_checksum,
                    "client_source_uri": store.source_uri(item.file_id),
                    "source_web_url": item.web_url,
                    "source_etag": item.etag,
                }
                source_uri = store.source_uri(item.file_id)
                if canonical_store is not None:
                    source_uri = store_canonical_resume(canonical_store, entry.candidate_id, local)
                if scope is None:
                    outcome = pipeline.ingest_resume(
                        entry.candidate_id, local, source_uri, metadata,
                    )
                else:
                    outcome = pipeline.ingest_resume(
                        entry.candidate_id, local, source_uri, metadata, scope=scope,
                    )
                # Treat legacy/custom pipelines without an explicit result as a completed embed.
                outcome = outcome or IngestionOutcome.EMBEDDED
                if outcome == IngestionOutcome.UNCHANGED:
                    report.unchanged += 1
                    progress(f"[{position}/{len(entries)}] unchanged {entry.candidate_id}")
                else:
                    report.embedded += 1
                    progress(f"[{position}/{len(entries)}] embedded {entry.candidate_id}")
            except Exception as error:  # noqa: BLE001 - isolate individual file failures
                failure = f"{entry.candidate_id}: {error}"
                report.failures.append(failure)
                progress(f"[{position}/{len(entries)}] failed {entry.candidate_id}")
            finally:
                if local is not None:
                    local.unlink(missing_ok=True)
            if on_result:
                on_result(entry.candidate_id, outcome if failure is None else None, failure)
    return report


def ingest_drive_folder(
    pipeline: ResumePipeline,
    store: FolderSource,
    folder_id: str,
    manifest_path: Path,
    progress: Callable[[str], None] | None = None,
    canonical_store: CanonicalObjectStore | None = None,
    scope: RecruiterScope | None = None,
) -> BatchReport:
    return ingest_source_folder(
        pipeline, store, folder_id, manifest_path, "drive_file_id", "Drive", progress,
        canonical_store, scope,
    )


def ingest_sharepoint_folder(
    pipeline: ResumePipeline,
    store: FolderSource,
    folder_url: str,
    manifest_path: Path,
    progress: Callable[[str], None] | None = None,
    canonical_store: CanonicalObjectStore | None = None,
    scope: RecruiterScope | None = None,
) -> BatchReport:
    return ingest_source_folder(
        pipeline, store, folder_url, manifest_path, "sharepoint_file_id", "SharePoint",
        progress, canonical_store, scope,
    )
