BEGIN;

UPDATE drive_watch_folders
SET notification_schedule = 'daily', next_scan_at = now()
WHERE notification_schedule = 'weekdays';

ALTER TABLE drive_watch_folders
    DROP CONSTRAINT IF EXISTS drive_watch_schedule_valid;

ALTER TABLE drive_watch_folders
    ADD CONSTRAINT drive_watch_schedule_valid
    CHECK (notification_schedule IN ('instant', 'daily', 'weekends'));

COMMIT;
