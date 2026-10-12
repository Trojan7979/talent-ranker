CREATE TABLE IF NOT EXISTS sharepoint_ingestion_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL UNIQUE,
    folder_url text NOT NULL,
    entries jsonb NOT NULL,
    created_by text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed')),
    discovered integer NOT NULL DEFAULT 0,
    indexed integer NOT NULL DEFAULT 0,
    skipped integer NOT NULL DEFAULT 0,
    failures jsonb NOT NULL DEFAULT '[]'::jsonb,
    attempts integer NOT NULL DEFAULT 0,
    leased_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS sharepoint_ingestion_jobs_claim_idx
  ON sharepoint_ingestion_jobs (created_at)
  WHERE status IN ('pending', 'running');
