ALTER TABLE resume_chunks
  ADD COLUMN IF NOT EXISTS parent_ordinal integer,
  ADD COLUMN IF NOT EXISTS parent_content text,
  ADD COLUMN IF NOT EXISTS chunk_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE resume_chunks
SET parent_ordinal = ordinal,
    parent_content = content
WHERE parent_ordinal IS NULL OR parent_content IS NULL;

ALTER TABLE resume_chunks
  ALTER COLUMN parent_ordinal SET NOT NULL,
  ALTER COLUMN parent_content SET NOT NULL;
