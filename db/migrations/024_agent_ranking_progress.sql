ALTER TABLE agent_ranking_jobs
  ADD COLUMN IF NOT EXISTS progress_message text;
ALTER TABLE agent_ranking_jobs
  ADD COLUMN IF NOT EXISTS progress_events jsonb NOT NULL DEFAULT '[]'::jsonb;
