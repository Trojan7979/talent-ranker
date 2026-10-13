CREATE TABLE IF NOT EXISTS agent_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL,
    actor_id text NOT NULL,
    job_id text NOT NULL REFERENCES jobs(job_id),
    ranking_run_id uuid REFERENCES ranking_runs(run_id),
    campaign_id uuid REFERENCES screening_campaigns(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_sessions_actor_idx
    ON agent_sessions (workspace_id, actor_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_messages_session_idx
    ON agent_messages (session_id, id);
