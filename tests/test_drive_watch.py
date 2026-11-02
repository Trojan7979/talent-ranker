"""Drive watch state must survive scans without duplicate recruiter alerts."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from sieve_app.drive_watch import DriveWatchStore
from sieve_app.indexing_store import IndexingStore
from talent_ranker.storage import DriveFile


@pytest.mark.integration
def test_drive_watch_baseline_updates_and_actor_inbox():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = "drive_watch_test_" + uuid4().hex
    migrations = Path(__file__).resolve().parents[1] / "db/migrations"
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            admin.execute(f'SET search_path TO "{schema}"')
            for name in ("011_drive_watch.sql", "012_drive_watch_schedules.sql",
                         "013_remove_weekday_drive_watch_schedule.sql"):
                admin.execute((migrations / name).read_text(encoding="utf-8"))
            index_store = IndexingStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
            try:
                store = DriveWatchStore(index_store.pool)
                first = DriveFile("one", "one.pdf", "t1", "hash-one", 100)
                watch = store.register("demo", "recruiter", "https://drive.google.com/drive/folders/x", [first])
                assert watch["notification_schedule"] == "instant"
                later = datetime.now(UTC) + timedelta(hours=1)
                updated_watch = store.set_schedule(
                    "demo", "recruiter", watch["folder_url"], "daily", "Asia/Kolkata", later,
                )
                assert updated_watch["id"] == watch["id"]
                assert updated_watch["notification_schedule"] == "daily"
                assert store.set_schedule("demo", "other", watch["folder_url"],
                                          "instant", "UTC", later) is None
                assert store.due_watches(datetime.now(UTC)) == []
                assert store.record_scan(watch["id"], [first]) == 0
                second = DriveFile("two", "two.docx", "t2", "hash-two", 200)
                assert store.record_scan(watch["id"], [first, second]) == 1
                assert store.record_scan(watch["id"], [first, second]) == 0
                updated = DriveFile("two", "two.docx", "t3", "hash-three", 210)
                assert store.record_scan(watch["id"], [first, updated]) == 1
                assert len(store.inbox("demo", "recruiter")["alerts"]) == 1
                assert store.inbox("demo", "other")["alerts"] == []
                alert_id = store.inbox("demo", "recruiter")["alerts"][0]["id"]
                assert not store.dismiss(alert_id, "demo", "other")
                assert store.dismiss(alert_id, "demo", "recruiter")
                assert store.inbox("demo", "recruiter")["alerts"] == []
            finally:
                index_store.close()
        finally:
            admin.execute("SET search_path TO public")
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
