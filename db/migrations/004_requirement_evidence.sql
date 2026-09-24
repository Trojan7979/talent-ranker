ALTER TABLE ranking_results
ADD COLUMN IF NOT EXISTS requirement_evidence jsonb NOT NULL DEFAULT '[]'::jsonb;
