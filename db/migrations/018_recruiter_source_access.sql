-- Existing rows remain unassigned until an explicit, reviewed legacy backfill.
CREATE TABLE IF NOT EXISTS candidate_source_grants (
    candidate_id text NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    workspace_id text NOT NULL,
    actor_id text NOT NULL,
    source_uri text NOT NULL,
    grant_kind text NOT NULL CHECK (grant_kind IN ('owner', 'shared')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, workspace_id, actor_id)
);
CREATE INDEX IF NOT EXISTS candidate_source_grants_actor_idx
    ON candidate_source_grants (workspace_id, actor_id, candidate_id);

ALTER TABLE ranking_runs ADD COLUMN IF NOT EXISTS workspace_id text;
ALTER TABLE ranking_runs ADD COLUMN IF NOT EXISTS actor_id text;
CREATE INDEX IF NOT EXISTS ranking_runs_actor_recent_idx
    ON ranking_runs (workspace_id, actor_id, created_at DESC, run_id DESC);
