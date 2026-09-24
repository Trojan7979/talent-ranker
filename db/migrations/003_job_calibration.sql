CREATE TABLE IF NOT EXISTS jobs (
    job_id text PRIMARY KEY,
    job_description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_profile_versions (
    profile_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    version integer NOT NULL,
    status text NOT NULL DEFAULT 'draft'
      CHECK (status IN ('draft', 'approved', 'superseded')),
    job_description text NOT NULL,
    priorities jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    approved_by text,
    UNIQUE(job_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_approved_profile_per_job_idx
  ON job_profile_versions(job_id) WHERE status = 'approved';

ALTER TABLE ranking_runs
  ADD COLUMN IF NOT EXISTS job_profile_version_id uuid
    REFERENCES job_profile_versions(profile_version_id);

CREATE INDEX IF NOT EXISTS ranking_runs_profile_version_idx
  ON ranking_runs(job_profile_version_id);
