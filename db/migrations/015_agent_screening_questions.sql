ALTER TABLE agent_sessions
  ADD COLUMN IF NOT EXISTS question_draft jsonb,
  ADD COLUMN IF NOT EXISTS question_profile_version_id uuid REFERENCES job_profile_versions(profile_version_id),
  ADD COLUMN IF NOT EXISTS question_top_n integer CHECK (question_top_n BETWEEN 1 AND 100),
  ADD COLUMN IF NOT EXISTS question_draft_revision integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS question_config_id uuid REFERENCES screening_job_configs(id);
