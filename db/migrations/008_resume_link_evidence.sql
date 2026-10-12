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
