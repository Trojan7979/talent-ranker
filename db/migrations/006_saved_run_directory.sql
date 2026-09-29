CREATE INDEX IF NOT EXISTS ranking_runs_recent_idx
  ON ranking_runs(created_at DESC, run_id DESC);

CREATE INDEX IF NOT EXISTS ranking_runs_job_recent_idx
  ON ranking_runs(job_id, created_at DESC, run_id DESC);
