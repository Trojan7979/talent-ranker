CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id text PRIMARY KEY,
    source_uri text NOT NULL,
    source_sha256 text NOT NULL UNIQUE,
    raw_text text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    consent_status text NOT NULL DEFAULT 'received',
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS resume_chunks (
    chunk_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id text NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    section text NOT NULL,
    content text NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS
      (to_tsvector('english', coalesce(section, '') || ' ' || content)) STORED,
    embedding vector(384) NOT NULL,
    UNIQUE(candidate_id, ordinal)
);

CREATE INDEX IF NOT EXISTS resume_chunks_tsv_idx
  ON resume_chunks USING gin(content_tsv);
CREATE INDEX IF NOT EXISTS resume_chunks_embedding_hnsw_idx
  ON resume_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);
CREATE INDEX IF NOT EXISTS resume_chunks_candidate_idx ON resume_chunks(candidate_id);

CREATE TABLE IF NOT EXISTS ranking_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text NOT NULL,
    jd_text text NOT NULL,
    model_versions jsonb NOT NULL,
    scoring_config jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ranking_results (
    run_id uuid NOT NULL REFERENCES ranking_runs(run_id) ON DELETE CASCADE,
    candidate_id text NOT NULL REFERENCES candidates(candidate_id),
    rank integer NOT NULL,
    score double precision NOT NULL,
    score_components jsonb NOT NULL,
    evidence jsonb NOT NULL,
    reasoning text NOT NULL,
    PRIMARY KEY(run_id, candidate_id),
    UNIQUE(run_id, rank)
);