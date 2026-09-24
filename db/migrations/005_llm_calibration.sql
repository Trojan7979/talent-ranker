ALTER TABLE job_profile_versions
ADD COLUMN IF NOT EXISTS calibration_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
