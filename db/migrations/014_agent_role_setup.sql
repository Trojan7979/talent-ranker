ALTER TABLE agent_sessions
  ADD COLUMN IF NOT EXISTS setup_stage text NOT NULL DEFAULT 'awaiting_jd'
    CHECK (setup_stage IN ('awaiting_jd', 'awaiting_jd_approval',
      'awaiting_criteria_approval', 'ranked')),
  ADD COLUMN IF NOT EXISTS draft_job_description text,
  ADD COLUMN IF NOT EXISTS draft_profile_version_id uuid REFERENCES job_profile_versions(profile_version_id);

UPDATE agent_sessions SET setup_stage = 'ranked' WHERE ranking_run_id IS NOT NULL;
