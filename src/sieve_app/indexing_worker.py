"""Resume queued SharePoint indexing jobs independently of the web server."""

from __future__ import annotations

import argparse
import hashlib
import logging
import tempfile
from pathlib import Path
from threading import Event
from uuid import UUID

from talent_ranker.access import RecruiterScope
from talent_ranker.batch_ingestion import IngestionOutcome, ManifestEntry, ingest_source_entries
from talent_ranker.config import SETTINGS
from talent_ranker.documents import extract_resume
from talent_ranker.drive_source import configured_drive_source
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.sharepoint import configured_sharepoint_source

from .agent_config import AgentSettings
from .drive_account import token_file
from .indexing_store import IndexingStore
from .resume_identity import extract_identity

logger = logging.getLogger(__name__)


def _progress_interval(total: int) -> int:
    """Keep long jobs visible without printing one line per resume."""
    return max(1, (total + 9) // 10)


class IndexingWorker:
    def __init__(self, store: IndexingStore, pipeline: RankingPipeline,
                 actor_id: str | None = None):
        self.store = store
        self.pipeline = pipeline
        self.actor_id = actor_id

    def run_once(self) -> bool:
        job = (self.store.claim_next(self.actor_id) if self.actor_id is not None
               else self.store.claim_next())
        if job is None:
            return False
        logger.info(
            "Processing resume %s job %s for recruiter %s",
            job["phase"], job["id"], job.get("created_by", "unknown"),
        )
        try:
            is_drive = job["folder_url"].startswith("https://drive.google.com/")
            source = (configured_drive_source(interactive=False, token_file=token_file(job["created_by"]))
                      if is_drive else configured_sharepoint_source(SETTINGS))
            if job["phase"] == "analyze":
                self._analyze(job, source)
            else:
                self._index(job, source, "drive" if is_drive else "sharepoint")
        except Exception:
            logger.exception("Resume indexing job %s failed", job["id"])
            self.store.fail(job["id"], job["attempts"],
                            "Resume indexing job failed; check worker logs")
        return True

    def _analyze(self, job, source) -> None:
        logger.info("Discovering resumes in the selected source folder.")
        files = source.list_resumes(job["folder_url"])
        if len(files) > 1000:
            raise ValueError("folder has more than 1000 resumes")
        logger.info("Analyzing %s resumes for candidate identity review.", len(files))
        drafts = []
        with tempfile.TemporaryDirectory(prefix="sieve-resume-review-") as directory:
            for position, file in enumerate(files, 1):
                draft = {"object_id": file.file_id, "file_name": file.name,
                         "source_uri": source.source_uri(file.file_id),
                         "web_url": file.web_url,
                         "name": None, "email": None, "job_title": None, "sha256": ""}
                try:
                    local = Path(directory) / f"resume{Path(file.name).suffix.lower()}"
                    source.download(file.file_id, local)
                    draft["sha256"] = hashlib.sha256(local.read_bytes()).hexdigest()
                    identity = extract_identity(extract_resume(local))
                    draft["name"], draft["email"] = identity.name, identity.email
                    draft["job_title"] = identity.job_title
                except Exception:
                    logger.exception("Could not analyze resume file %s", file.file_id)
                    draft["analysis_error"] = "Could not extract text; check file or provide OCR"
                finally:
                    local.unlink(missing_ok=True)
                drafts.append(draft)
                if position % _progress_interval(len(files)) == 0 or position == len(files):
                    logger.info("Resume analysis progress: %s/%s checked.", position, len(files))
        drafts = self.store.match_candidates(drafts)
        self.store.save_analysis(job["id"], job["attempts"], drafts)
        logger.info(
            "Resume analysis ready for review: %s checked, %s matched existing, "
            "%s new, %s need review.",
            len(drafts), sum(item.get("suggestion") == "existing" for item in drafts),
            sum(item.get("suggestion") == "new" for item in drafts),
            sum(item.get("suggestion") == "review" for item in drafts),
        )

    def _index(self, job, source, source_kind="sharepoint") -> None:
        entries_by_id = {item["candidate_id"]: item for item in job["entries"]}
        entries = [ManifestEntry(item["candidate_id"], item["object_id"],
                                 metadata={"job_title": item.get("job_title", "")},
                                 expected_sha256=item.get("sha256"))
                   for item in job["entries"]]
        total = len(entries)
        counts = {"embedded": 0, "unchanged": 0, "failed": 0}
        processed = 0
        logger.info("Indexing %s selected %s resumes.", total, source_kind.title())
        logger.info("Checking the source folder before processing selected resumes.")

        def on_result(
            candidate_id: str, outcome: IngestionOutcome | None, failure: str | None,
        ) -> None:
            nonlocal processed
            if failure is None:
                item = entries_by_id[candidate_id]
                identity_args = (
                    job["id"], job["attempts"], candidate_id,
                    source.source_uri(item["object_id"]),
                    item.get("name", ""), item.get("email", ""), job["created_by"],
                )
                if source_kind == "drive":
                    self.store.record_identity(*identity_args, source_kind="drive")
                else:
                    self.store.record_identity(*identity_args)
            self.store.record_result(
                job["id"], job["attempts"],
                f"{candidate_id}: indexing failed; check worker logs" if failure else None,
                outcome=outcome,
            )
            processed += 1
            key = ("failed" if failure else "unchanged"
                   if outcome == IngestionOutcome.UNCHANGED else "embedded")
            counts[key] += 1
            if processed % _progress_interval(total) == 0 or processed == total:
                logger.info(
                    "Resume indexing progress: %s/%s processed (%s newly embedded, "
                    "%s unchanged, %s failed).",
                    processed, total, counts["embedded"], counts["unchanged"], counts["failed"],
                )

        report = ingest_source_entries(
            self.pipeline,
            source,
            job["folder_url"],
            entries,
            source_kind.title(),
            on_result=on_result,
            scope=RecruiterScope(
                AgentSettings().workspace_id, job["created_by"], frozenset()
            ),
        )
        self.store.finish(job["id"], job["attempts"], report.discovered, report.skipped)
        logger.info(
            "Resume indexing completed: %s selected, %s newly embedded, %s unchanged, "
            "%s failed; %s source files not selected.",
            total, report.embedded, report.unchanged, len(report.failures), report.skipped,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued SharePoint indexing jobs")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--actor-id", type=UUID,
                        help="process only jobs submitted by this signed-in recruiter")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info(
        "Indexing worker started (mode=%s, poll_interval=%.1fs, recruiter_scope=%s)",
        "one job" if args.once else "continuous",
        args.interval,
        str(args.actor_id) if args.actor_id else "all valid recruiters",
    )
    store = IndexingStore(SETTINGS.database_url)
    pipeline = RankingPipeline(SETTINGS)
    try:
        worker = IndexingWorker(store, pipeline,
                                str(args.actor_id) if args.actor_id else None)
        if args.once:
            worker.run_once()
        else:
            stop = Event()
            while not stop.is_set():
                if not worker.run_once():
                    stop.wait(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.repo.close()
        store.close()


if __name__ == "__main__":
    main()
