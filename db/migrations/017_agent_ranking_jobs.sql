ALTER TABLE agent_sessions DROP CONSTRAINT IF EXISTS agent_sessions_setup_stage_check;
ALTER TABLE agent_sessions ADD CONSTRAINT agent_sessions_setup_stage_check
  CHECK (setup_stage IN ('awaiting_jd', 'awaiting_jd_approval',
    'awaiting_criteria_approval', 'ranking', 'ranked'));

CREATE TABLE IF NOT EXISTS agent_ranking_jobs (
  session_id uuid PRIMARY KEY REFERENCES agent_sessions(id) ON DELETE CASCADE,
  profile_version_id uuid NOT NULL REFERENCES job_profile_versions(profile_version_id),
  top_k integer NOT NULL CHECK (top_k BETWEEN 1 AND 1000),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  attempts integer NOT NULL DEFAULT 0,
  leased_until timestamptz,
  run_id uuid REFERENCES ranking_runs(run_id),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_ranking_jobs_ready_idx
  ON agent_ranking_jobs (created_at)
  WHERE status IN ('pending', 'running');
