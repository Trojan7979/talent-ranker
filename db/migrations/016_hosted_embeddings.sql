ALTER TABLE resume_chunks ADD COLUMN IF NOT EXISTS embedding_v2 vector(1024);
ALTER TABLE resume_chunks ALTER COLUMN embedding DROP NOT NULL;
ALTER TABLE resume_chunks DROP CONSTRAINT IF EXISTS resume_chunks_has_embedding;
ALTER TABLE resume_chunks ADD CONSTRAINT resume_chunks_has_embedding
  CHECK (embedding IS NOT NULL OR embedding_v2 IS NOT NULL);
CREATE INDEX IF NOT EXISTS resume_chunks_embedding_v2_hnsw_idx
  ON resume_chunks USING hnsw (embedding_v2 vector_cosine_ops)
  WITH (m = 16, ef_construction = 128) WHERE embedding_v2 IS NOT NULL;
