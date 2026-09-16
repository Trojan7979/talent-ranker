from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import tempfile

from .config import SETTINGS
from .pipeline import RankingPipeline


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
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="talent-ranker")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Extract, chunk, embed and index a resume PDF")
    ingest.add_argument("candidate_id")
    ingest.add_argument("pdf", type=Path)
    ingest.add_argument("--source-uri")
    ingest.add_argument("--metadata", type=Path, help="ATS/platform metadata JSON")
    ingest_drive = sub.add_parser("ingest-drive", help="Fetch a Google Drive PDF and index it")
    ingest_drive.add_argument("candidate_id")
    ingest_drive.add_argument("file_id")
    ingest_drive.add_argument("--metadata", type=Path, help="ATS/platform metadata JSON")
    rank = sub.add_parser("rank", help="Rank indexed candidates for a job description")
    rank.add_argument("--job-id", required=True)
    rank.add_argument("--jd", type=Path, required=True)
    rank.add_argument("--output", type=Path, default=Path("ranking.csv"))
    rank.add_argument("--top-k", type=int, default=100)
    args = parser.parse_args()
    pipeline = RankingPipeline(SETTINGS)
    try:
        metadata = (
            json.loads(args.metadata.read_text(encoding="utf-8"))
            if getattr(args, "metadata", None)
            else None
        )
        if args.command == "ingest":
            pipeline.ingest_pdf(args.candidate_id, args.pdf, args.source_uri, metadata)
        elif args.command == "ingest-drive":
            from .storage import GoogleDriveStore

            with tempfile.TemporaryDirectory(prefix="talent-ranker-ingest-") as directory:
                local = Path(directory) / "resume.pdf"
                store = GoogleDriveStore(
                    Path(SETTINGS.google_credentials_file), Path(SETTINGS.google_token_file)
                )
                store.download(args.file_id, local)
                pipeline.ingest_pdf(args.candidate_id, local, f"gdrive://{args.file_id}", metadata)
        else:
            run_id, results = pipeline.rank(
                args.job_id, args.jd.read_text(encoding="utf-8"), args.top_k
            )
            write_outputs(results, args.output)
            print(f"saved run {run_id}: {args.output} and {args.output.with_suffix('.jsonl')}")
    finally:
        pipeline.repo.close()


if __name__ == "__main__":
    main()
