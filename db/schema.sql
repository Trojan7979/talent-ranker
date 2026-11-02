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
    parent_ordinal integer NOT NULL,
    section text NOT NULL,
    content text NOT NULL,
    parent_content text NOT NULL,
    chunk_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    content_tsv tsvector GENERATED ALWAYS AS
      (to_tsvector('english', coalesce(section, '') || ' ' || content)) STORED,
    embedding_v2 vector(1024) NOT NULL,
    UNIQUE(candidate_id, ordinal)
);

CREATE INDEX IF NOT EXISTS resume_chunks_tsv_idx
  ON resume_chunks USING gin(content_tsv);
CREATE INDEX IF NOT EXISTS resume_chunks_embedding_v2_hnsw_idx
  ON resume_chunks USING hnsw (embedding_v2 vector_cosine_ops)
  WITH (m = 16, ef_construction = 128) WHERE embedding_v2 IS NOT NULL;
CREATE INDEX IF NOT EXISTS resume_chunks_candidate_idx ON resume_chunks(candidate_id);

CREATE TABLE IF NOT EXISTS candidate_source_grants (
    candidate_id text NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    workspace_id text NOT NULL,
    actor_id text NOT NULL,
    source_uri text NOT NULL,
    grant_kind text NOT NULL CHECK (grant_kind IN ('owner', 'shared')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, workspace_id, actor_id)
);
CREATE INDEX IF NOT EXISTS candidate_source_grants_actor_idx
  ON candidate_source_grants(workspace_id, actor_id, candidate_id);

CREATE TABLE IF NOT EXISTS drive_oauth_states (
    state_hash text PRIMARY KEY,
    actor text NOT NULL,
    code_verifier text NOT NULL,
    nonce text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS drive_oauth_states_expiry_idx
  ON drive_oauth_states(expires_at);

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
ALTER TABLE sharepoint_ingestion_jobs
  ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'index';
ALTER TABLE sharepoint_ingestion_jobs DROP CONSTRAINT IF EXISTS sharepoint_ingestion_jobs_status_check;
ALTER TABLE sharepoint_ingestion_jobs ADD CONSTRAINT sharepoint_ingestion_jobs_status_check
  CHECK (status IN ('pending', 'running', 'awaiting_review', 'completed', 'completed_with_errors', 'failed'));
CREATE INDEX IF NOT EXISTS sharepoint_ingestion_jobs_claim_idx
  ON sharepoint_ingestion_jobs (created_at)
  WHERE status IN ('pending', 'running');

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
    calibration_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    approved_by text,
    UNIQUE(job_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_approved_profile_per_job_idx
  ON job_profile_versions(job_id) WHERE status = 'approved';

CREATE TABLE IF NOT EXISTS ranking_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text NOT NULL,
    job_profile_version_id uuid REFERENCES job_profile_versions(profile_version_id),
    jd_text text NOT NULL,
    model_versions jsonb NOT NULL,
    scoring_config jsonb NOT NULL,
    workspace_id text,
    actor_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ranking_runs_profile_version_idx
  ON ranking_runs(job_profile_version_id);
CREATE INDEX IF NOT EXISTS ranking_runs_recent_idx
  ON ranking_runs(created_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS ranking_runs_job_recent_idx
  ON ranking_runs(job_id, created_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS ranking_runs_actor_recent_idx
  ON ranking_runs(workspace_id, actor_id, created_at DESC, run_id DESC);

CREATE TABLE IF NOT EXISTS ranking_results (
    run_id uuid NOT NULL REFERENCES ranking_runs(run_id) ON DELETE CASCADE,
    candidate_id text NOT NULL REFERENCES candidates(candidate_id),
    rank integer NOT NULL,
    score double precision NOT NULL,
    score_components jsonb NOT NULL,
    evidence jsonb NOT NULL,
    requirement_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    reasoning text NOT NULL,
    PRIMARY KEY(run_id, candidate_id),
    UNIQUE(run_id, rank)
);
-- Link discovery and a durable enrichment queue share one bounded record per URL.
CREATE TABLE IF NOT EXISTS candidate_external_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id text NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    source_sha256 text NOT NULL,
    url text NOT NULL CHECK (length(url) <= 2048),
    kind text NOT NULL CHECK (kind IN ('github', 'web', 'unsupported')),
    discovered_via text NOT NULL CHECK (discovered_via IN ('text', 'hyperlink')),
    status text NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending', 'running', 'completed', 'failed', 'blocked', 'unsupported')),
    attempts integer NOT NULL DEFAULT 0,
    lease_token uuid,
    leased_until timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    fetched_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(candidate_id, url)
);
CREATE INDEX IF NOT EXISTS external_evidence_claim_idx
  ON candidate_external_evidence(next_attempt_at, created_at)
  WHERE status IN ('pending', 'running');

CREATE TABLE IF NOT EXISTS recruiter_identities (
  recruiter_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL CHECK (provider IN ('google', 'microsoft')),
  issuer text NOT NULL,
  subject text NOT NULL,
  email text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(provider, issuer, subject)
);
CREATE TABLE IF NOT EXISTS recruiter_login_states (
  state_hash text PRIMARY KEY,
  provider text NOT NULL,
  verifier text NOT NULL,
  nonce text NOT NULL,
  expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS recruiter_sessions (
  token_hash text PRIMARY KEY,
  recruiter_id uuid NOT NULL REFERENCES recruiter_identities(recruiter_id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recruiter_sessions_actor_idx ON recruiter_sessions(recruiter_id);
CREATE TABLE IF NOT EXISTS recruiter_job_grants (
  workspace_id text NOT NULL,
  recruiter_id uuid NOT NULL REFERENCES recruiter_identities(recruiter_id) ON DELETE CASCADE,
  job_id text NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id, recruiter_id, job_id)
);
