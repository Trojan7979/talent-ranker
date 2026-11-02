CREATE TABLE IF NOT EXISTS drive_watch_folders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL,
    actor_id text NOT NULL,
    folder_url text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_scan_at timestamptz,
    last_error text,
    UNIQUE (workspace_id, actor_id, folder_url)
);

CREATE TABLE IF NOT EXISTS drive_watch_files (
    watch_id uuid NOT NULL REFERENCES drive_watch_folders(id) ON DELETE CASCADE,
    file_id text NOT NULL,
    version text NOT NULL,
    name text NOT NULL,
    modified_at text NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (watch_id, file_id)
);

CREATE TABLE IF NOT EXISTS drive_watch_alerts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    watch_id uuid NOT NULL REFERENCES drive_watch_folders(id) ON DELETE CASCADE,
    file_id text NOT NULL,
    version text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('pdf', 'docx')),
    created_at timestamptz NOT NULL DEFAULT now(),
    dismissed_at timestamptz,
    UNIQUE (watch_id, file_id, version)
);

CREATE INDEX IF NOT EXISTS drive_watch_alerts_pending_idx
    ON drive_watch_alerts (watch_id, created_at DESC) WHERE dismissed_at IS NULL;
