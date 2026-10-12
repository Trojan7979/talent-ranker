ALTER TABLE sharepoint_ingestion_jobs
  ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'index';
ALTER TABLE sharepoint_ingestion_jobs DROP CONSTRAINT IF EXISTS sharepoint_ingestion_jobs_status_check;
ALTER TABLE sharepoint_ingestion_jobs ADD CONSTRAINT sharepoint_ingestion_jobs_status_check
  CHECK (status IN ('pending', 'running', 'awaiting_review', 'completed', 'completed_with_errors', 'failed'));

CREATE TABLE IF NOT EXISTS candidate_names (
    candidate_id text PRIMARY KEY REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    display_name text NOT NULL,
    source text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sharepoint_candidate_files (
    source_uri text PRIMARY KEY,
    candidate_id text NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sharepoint_candidate_files_candidate_idx
  ON sharepoint_candidate_files(candidate_id);
CREATE TABLE IF NOT EXISTS candidate_id_allocations (
    candidate_number integer PRIMARY KEY CHECK (candidate_number BETWEEN 1 AND 9000),
    job_id uuid NOT NULL REFERENCES sharepoint_ingestion_jobs(id)
);
