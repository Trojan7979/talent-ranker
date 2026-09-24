from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from talent_ranker.config import SETTINGS
from talent_ranker.pipeline import RankingPipeline


def local_path(source_uri: str) -> Path:
    parsed = urlparse(source_uri)
    if parsed.scheme != "file":
        raise ValueError(f"unsupported source scheme: {parsed.scheme or 'missing'}")
    return Path(unquote(parsed.path.lstrip("/")))


def main() -> int:
    pipeline = RankingPipeline(SETTINGS)
    failures: list[tuple[str, str]] = []
    try:
        rows = pipeline.repo.conn.execute(
            """SELECT candidate_id, source_uri, metadata
               FROM candidates WHERE deleted_at IS NULL ORDER BY candidate_id"""
        ).fetchall()
        pipeline.repo.conn.rollback()
        print(f"reindexing {len(rows)} candidates")
        for position, (candidate_id, source_uri, metadata) in enumerate(rows, 1):
            try:
                path = local_path(source_uri)
                if not path.is_file():
                    raise FileNotFoundError("source PDF is unavailable")
                pipeline.ingest_pdf(candidate_id, path, source_uri, metadata)
                print(f"[{position}/{len(rows)}] reindexed {candidate_id}")
            except Exception as error: # noqa: BLE001
                failures.append((candidate_id, type(error).__name__))
                print(f"[{position}/{len(rows)}] failed {candidate_id}: {type(error).__name__}")
    finally:
        pipeline.repo.close()
    print(f"complete: {len(rows) - len(failures)} reindexed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
