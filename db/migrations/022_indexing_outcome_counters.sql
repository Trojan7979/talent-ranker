ALTER TABLE sharepoint_ingestion_jobs
  ADD COLUMN IF NOT EXISTS analyzed integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS matched_existing integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS unchanged integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS embedded integer NOT NULL DEFAULT 0;

-- Preserve useful analysis counts for reviews created immediately before deployment.
UPDATE sharepoint_ingestion_jobs AS jobs
SET analyzed = jobs.discovered,
    matched_existing = (
      SELECT count(*) FROM jsonb_array_elements(jobs.entries) AS entry
      WHERE entry->>'suggestion' = 'existing'
    )
WHERE jobs.phase = 'analyze' AND jobs.status = 'awaiting_review'
  AND jobs.analyzed = 0;
