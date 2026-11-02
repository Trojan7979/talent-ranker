"""Scan registered Drive folders independently of the API and chat browser."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Event

from talent_ranker.config import SETTINGS
from talent_ranker.drive_source import configured_drive_source
from talent_ranker.storage import DriveConnectionError

from .drive_account import token_file
from .drive_watch import DriveWatchStore
from .indexing_store import IndexingStore

logger = logging.getLogger(__name__)


CHECK_INTERVAL_SECONDS = 2.0


def run_once(store: DriveWatchStore, source, watches: list[dict]) -> int:
    detected = 0
    for watch in watches:
        try:
            files = source.list_resumes(watch["folder_url"])
            if len(files) > 1000:
                raise ValueError("Drive folder has more than 1000 resumes")
            detected += store.record_scan(watch["id"], files)
        except Exception:
            logger.exception("Drive watch %s failed", watch["id"])
            store.record_error(watch["id"], "Drive scan failed; reconnect Drive or check worker logs")
    return detected


def main() -> None:
    index_store = IndexingStore(SETTINGS.database_url)
    try:
        watches = DriveWatchStore(index_store.pool)

        def scan() -> int | None:
            due = watches.due_watches(datetime.now(UTC))
            if not due:
                return 0
            detected = 0
            for watch in due:
                try:
                    source = configured_drive_source(
                        interactive=False, token_file=token_file(watch["actor_id"]))
                    detected += run_once(watches, source, [watch])
                except (DriveConnectionError, FileNotFoundError, ValueError):
                    logger.warning("Google Drive needs to be reconnected for watch %s", watch["id"])
                    watches.record_error(watch["id"], "Reconnect Google Drive in Resume sources")
            return detected

        stop = Event()
        while not stop.is_set():
            scan()
            stop.wait(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        index_store.close()


if __name__ == "__main__":
    main()
