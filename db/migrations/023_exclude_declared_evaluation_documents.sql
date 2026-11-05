-- Existing test artifacts explicitly declare that they are not job applications.
-- Keep their indexed data for audits while excluding them from new ranking pools.
UPDATE candidates
SET metadata = jsonb_set(metadata, '{document_kind}', '"evaluation"'::jsonb, true)
WHERE position('SYNTHETIC EVALUATION DOCUMENT' in upper(raw_text)) > 0
  AND coalesce(metadata->>'document_kind', 'resume') <> 'evaluation';
