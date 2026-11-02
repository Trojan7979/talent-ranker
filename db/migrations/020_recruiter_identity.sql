CREATE TABLE IF NOT EXISTS recruiter_identities (
    recruiter_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL CHECK (provider IN ('google', 'microsoft')),
    issuer text NOT NULL,
    subject text NOT NULL,
    email text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, issuer, subject)
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
    PRIMARY KEY (workspace_id, recruiter_id, job_id)
);
