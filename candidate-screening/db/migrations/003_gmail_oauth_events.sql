CREATE TABLE IF NOT EXISTS screening_gmail_oauth_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    state_hash text NOT NULL,
    event text NOT NULL,
    detail text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS screening_gmail_oauth_events_created_idx
    ON screening_gmail_oauth_events (created_at);
