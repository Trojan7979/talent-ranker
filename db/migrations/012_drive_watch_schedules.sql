ALTER TABLE drive_watch_folders
    ADD COLUMN IF NOT EXISTS notification_schedule text NOT NULL DEFAULT 'instant',
    ADD COLUMN IF NOT EXISTS notification_timezone text NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS next_scan_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE drive_watch_folders
    ADD CONSTRAINT drive_watch_schedule_valid
    CHECK (notification_schedule IN ('instant', 'daily', 'weekdays', 'weekends'));

CREATE INDEX IF NOT EXISTS drive_watch_folders_due_idx
    ON drive_watch_folders (next_scan_at);
