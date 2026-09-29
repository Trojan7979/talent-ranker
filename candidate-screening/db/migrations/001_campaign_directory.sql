CREATE INDEX IF NOT EXISTS screening_campaigns_recent_idx
    ON screening_campaigns (created_at DESC, id DESC);
