"""Persist Google Drive folder snapshots and recruiter-visible change alerts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from psycopg.rows import dict_row

from .drive_watch_schedule import next_scan_at


def file_version(item) -> str:
    """Use source metadata so repeat scans do not create duplicate alerts."""
    return f"{item.md5_checksum}|{item.modified_time}|{item.size}"


class DriveWatchStore:
    def __init__(self, pool):
        self.pool = pool

    def register(self, workspace_id: str, actor: str, folder_url: str, files: list,
                 schedule: str = "instant", zone_name: str = "UTC", next_scan=None) -> dict:
        """Snapshot existing files as a baseline; only later changes become alerts."""
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """INSERT INTO drive_watch_folders
                   (workspace_id,actor_id,folder_url,last_scan_at,
                    notification_schedule,notification_timezone,next_scan_at)
                   VALUES (%s,%s,%s,now(),%s,%s,coalesce(%s,now()))
                   ON CONFLICT(workspace_id,actor_id,folder_url) DO NOTHING
                   RETURNING *""",
                (workspace_id, actor, folder_url, schedule, zone_name, next_scan),
            )
            created = cur.fetchone()
            if created is None:
                cur.execute(
                    """UPDATE drive_watch_folders SET notification_schedule=%s,
                       notification_timezone=%s,next_scan_at=%s
                       WHERE workspace_id=%s AND actor_id=%s AND folder_url=%s
                       RETURNING *""",
                    (schedule, zone_name, next_scan, workspace_id, actor, folder_url),
                )
                return cur.fetchone()
            for item in files:
                cur.execute(
                    """INSERT INTO drive_watch_files
                       (watch_id,file_id,version,name,modified_at)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (created["id"], item.file_id, file_version(item), item.name, item.modified_time),
                )
            return created

    def watches(self) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM drive_watch_folders ORDER BY created_at,id")
            return cur.fetchall()

    def set_schedule(self, workspace_id: str, actor: str, folder_url: str,
                     schedule: str, zone_name: str, next_scan) -> dict | None:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """UPDATE drive_watch_folders SET notification_schedule=%s,
                   notification_timezone=%s,next_scan_at=%s
                   WHERE workspace_id=%s AND actor_id=%s AND folder_url=%s
                   RETURNING *""",
                (schedule, zone_name, next_scan, workspace_id, actor, folder_url),
            )
            return cur.fetchone()

    def due_watches(self, now) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM drive_watch_folders WHERE next_scan_at <= %s ORDER BY next_scan_at,id",
                (now,),
            )
            return cur.fetchall()

    def record_scan(self, watch_id: UUID, files: list) -> int:
        """Compare one full scan atomically; repeated or concurrent scans stay idempotent."""
        added = 0
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT notification_schedule,notification_timezone
                   FROM drive_watch_folders WHERE id=%s FOR UPDATE""",
                (watch_id,),
            )
            watch = cur.fetchone()
            if watch is None:
                return 0
            for item in files:
                version = file_version(item)
                cur.execute(
                    """INSERT INTO drive_watch_files
                       (watch_id,file_id,version,name,modified_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT(watch_id,file_id) DO UPDATE SET
                         version=excluded.version,name=excluded.name,
                         modified_at=excluded.modified_at,seen_at=now()
                       WHERE drive_watch_files.version IS DISTINCT FROM excluded.version
                       RETURNING file_id""",
                    (watch_id, item.file_id, version, item.name, item.modified_time),
                )
                if cur.fetchone() is None:
                    continue
                kind = Path(item.name).suffix.lower().removeprefix(".")
                if kind not in {"pdf", "docx"}:
                    continue
                cur.execute(
                    """UPDATE drive_watch_alerts SET dismissed_at=now()
                       WHERE watch_id=%s AND file_id=%s AND dismissed_at IS NULL""",
                    (watch_id, item.file_id),
                )
                cur.execute(
                    """INSERT INTO drive_watch_alerts(watch_id,file_id,version,name,kind)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
                    (watch_id, item.file_id, version, item.name, kind),
                )
                added += int(cur.fetchone() is not None)
            cur.execute(
                """UPDATE drive_watch_folders SET last_scan_at=now(),last_error=NULL,
                     next_scan_at=%s
                   WHERE id=%s""",
                (next_scan_at(watch["notification_schedule"], watch["notification_timezone"],
                              datetime.now(UTC)), watch_id),
            )
        return added

    def record_error(self, watch_id: UUID, error: str) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE drive_watch_folders SET last_error=%s,
                     next_scan_at=now() + interval '1 minute' WHERE id=%s""",
                (error[:300], watch_id),
            )

    def inbox(self, workspace_id: str, actor: str) -> dict:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT * FROM drive_watch_folders
                   WHERE workspace_id=%s AND actor_id=%s ORDER BY created_at,id""",
                (workspace_id, actor),
            )
            watches = cur.fetchall()
            cur.execute(
                """SELECT a.id,a.file_id,a.name,a.kind,a.created_at,w.folder_url
                   FROM drive_watch_alerts a JOIN drive_watch_folders w ON w.id=a.watch_id
                   WHERE w.workspace_id=%s AND w.actor_id=%s AND a.dismissed_at IS NULL
                   ORDER BY a.id DESC LIMIT 100""",
                (workspace_id, actor),
            )
            alerts = cur.fetchall()
        return {"watches": watches, "alerts": alerts}

    def dismiss(self, alert_id: int, workspace_id: str, actor: str) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE drive_watch_alerts a SET dismissed_at=now()
                   FROM drive_watch_folders w
                   WHERE a.id=%s AND a.watch_id=w.id AND w.workspace_id=%s
                     AND w.actor_id=%s AND a.dismissed_at IS NULL""",
                (alert_id, workspace_id, actor),
            )
            return cur.rowcount == 1
