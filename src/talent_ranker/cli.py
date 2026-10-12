from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path

from .batch_ingestion import (
    ingest_drive_folder,
    ingest_sharepoint_folder,
    write_drive_inventory,
    write_inventory,
)
from .config import SETTINGS
from .drive_links import drive_id
from .pipeline import RankingPipeline
from .privacy_audit import audit_privacy
from .repository import PostgresRepository
from .sharepoint import SharePointFolderSource, configured_sharepoint_source
from .storage import (
    CanonicalObjectStore,
    GoogleDriveStore,
    configured_canonical_store,
    store_canonical_resume,
)


def write_outputs(results, output: Path) -> None:
    """CSV is the benchmark contract; JSONL is the lossless audit/export contract."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["candidate_id", "rank", "score", "reasoning"])
        writer.writeheader()
        for rank, result in enumerate(results, 1):
            writer.writerow(
                {
                    "candidate_id": result.candidate_id,
                    "rank": rank,
                    "score": f"{result.score:.6f}",
                    "reasoning": result.reasoning,
                }
            )
    audit = output.with_suffix(".jsonl")
    with audit.open("w", encoding="utf-8") as handle:
        for rank, result in enumerate(results, 1):
            row = {
                "candidate_id": result.candidate_id,
                "rank": rank,
                "score": result.score,
                "score_components": result.components,
                "evidence": result.evidence,
                "reasoning": result.reasoning,
                "requirement_evidence": result.requirement_evidence,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="talent-ranker")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Extract, chunk, embed and index a PDF or DOCX resume")
    ingest.add_argument("candidate_id")
    ingest.add_argument("resume", type=Path)
    ingest.add_argument("--source-uri")
    ingest.add_argument("--metadata", type=Path, help="ATS/platform metadata JSON")
    ingest_drive = sub.add_parser("ingest-drive", help="Fetch a Google Drive PDF or DOCX and index it")
    ingest_drive.add_argument("candidate_id")
    ingest_drive.add_argument("file_id", help="Drive file link or ID")
    ingest_drive.add_argument("--metadata", type=Path, help="ATS/platform metadata JSON")
    sub.add_parser("drive-authorize", help="Connect a Google Drive account for resume intake")
    inventory = sub.add_parser("drive-inventory", help="Export resumes in a Drive folder to CSV")
    inventory.add_argument("folder_id", help="Drive folder link or ID")
    inventory.add_argument("--output", type=Path, default=Path("drive_inventory.csv"))
    batch = sub.add_parser("ingest-drive-folder", help="Index mapped resumes from a Drive folder")
    batch.add_argument("folder_id", help="Drive folder link or ID")
    batch.add_argument("--manifest", type=Path, required=True)
    sp_inventory = sub.add_parser("sharepoint-inventory", help="Preview resumes in SharePoint")
    sp_inventory.add_argument("folder_url")
    sp_inventory.add_argument("--output", type=Path, default=Path("sharepoint_inventory.csv"))
    sp_batch = sub.add_parser("ingest-sharepoint-folder", help="Index mapped SharePoint resumes")
    sp_batch.add_argument("folder_url")
    sp_batch.add_argument("--manifest", type=Path, required=True)
    rank = sub.add_parser("rank", help="Rank indexed candidates for a job description")
    rank.add_argument("--job-id", required=True)
    rank.add_argument("--profile-version-id", required=True)
    rank.add_argument("--output", type=Path, default=Path("ranking.csv"))
    rank.add_argument("--top-k", type=int, default=100)
    audit = sub.add_parser("privacy-audit", help="Scan stored text for supported contact PII")
    audit.add_argument("--fail-on-findings", action="store_true")
    return parser


def drive_store() -> GoogleDriveStore:
    return GoogleDriveStore(
        Path(SETTINGS.google_credentials_file),
        Path(SETTINGS.google_token_file),
    )


def sharepoint_store() -> SharePointFolderSource:
    return configured_sharepoint_source(SETTINGS)


def canonical_store() -> CanonicalObjectStore:
    return configured_canonical_store(SETTINGS)


def read_metadata(path: Path | None) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def run_drive_inventory(folder_id: str, output: Path) -> None:
    files = drive_store().list_resumes(drive_id(folder_id, "folder"))
    write_drive_inventory(files, output)
    print(f"saved {len(files)} resumes to {output}")


def run_sharepoint_inventory(folder_url: str, output: Path) -> None:
    files = sharepoint_store().list_resumes(folder_url)
    write_inventory(files, output, "sharepoint_file_id")
    print(f"saved {len(files)} resumes to {output}")


def run_privacy_audit(fail_on_findings: bool) -> None:
    repository = PostgresRepository(SETTINGS.database_url)
    try:
        report = audit_privacy(repository.iter_privacy_texts())
    finally:
        repository.close()
    print(
        f"privacy audit: {report.finding_count} findings across "
        f"{report.affected_candidates} candidates"
    )
    for issue in report.issues:
        types = ",".join(issue.pii_types)
        print(f"{issue.candidate_id} {issue.field}: {issue.finding_count} ({types})")
    if fail_on_findings and report.finding_count:
        raise SystemExit(1)


def run_pipeline_command(args: argparse.Namespace) -> None:
    pipeline = RankingPipeline(SETTINGS)
    try:
        if args.command == "ingest":
            metadata = read_metadata(args.metadata) or {}
            metadata["client_source_uri"] = args.source_uri or args.resume.resolve().as_uri()
            pipeline.ingest_resume(
                args.candidate_id,
                args.resume,
                store_canonical_resume(canonical_store(), args.candidate_id, args.resume),
                metadata,
            )
        elif args.command == "ingest-drive":
            with tempfile.TemporaryDirectory(prefix="talent-ranker-ingest-") as directory:
                file_id = drive_id(args.file_id, "file")
                source_store = drive_store()
                local = Path(directory) / f"resume{Path(source_store.resume_name(file_id)).suffix.lower()}"
                source_store.download(file_id, local)
                source_uri = store_canonical_resume(canonical_store(), args.candidate_id, local)
                metadata = read_metadata(args.metadata) or {}
                metadata["client_source_uri"] = source_store.source_uri(file_id)
                pipeline.ingest_resume(
                    args.candidate_id,
                    local,
                    source_uri,
                    metadata,
                )
        elif args.command == "ingest-drive-folder":
            report = ingest_drive_folder(
                pipeline,
                drive_store(),
                drive_id(args.folder_id, "folder"),
                args.manifest,
                print,
                canonical_store(),
            )
            print(
                f"complete: {report.indexed} indexed, {len(report.failures)} failed, "
                f"{report.skipped} unmapped"
            )
            if report.failures:
                print("\n".join(report.failures))
                raise SystemExit(1)
        elif args.command == "ingest-sharepoint-folder":
            report = ingest_sharepoint_folder(
                pipeline, sharepoint_store(), args.folder_url, args.manifest, print,
            )
            print(
                f"complete: {report.indexed} indexed, {len(report.failures)} failed, "
                f"{report.skipped} unmapped"
            )
            if report.failures:
                print("\n".join(report.failures))
                raise SystemExit(1)
        else:
            profile = pipeline.repo.get_job_profile(args.profile_version_id)
            if profile is None:
                raise ValueError("job profile version not found")
            if profile["job_id"] != args.job_id:
                raise ValueError("job profile does not belong to requested job")
            if profile["status"] != "approved":
                raise ValueError("job profile must be approved before ranking")
            run_id, results = pipeline.rank(args.job_id, profile, args.top_k)
            write_outputs(results, args.output)
            print(f"saved run {run_id}: {args.output} and {args.output.with_suffix('.jsonl')}")
    finally:
        pipeline.repo.close()


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "drive-inventory":
        run_drive_inventory(args.folder_id, args.output)
        return
    if args.command == "drive-authorize":
        drive_store()
        print("Google Drive connected")
        return
    if args.command == "sharepoint-inventory":
        run_sharepoint_inventory(args.folder_url, args.output)
        return
    if args.command == "privacy-audit":
        run_privacy_audit(args.fail_on_findings)
        return
    run_pipeline_command(args)


if __name__ == "__main__":
    main()
