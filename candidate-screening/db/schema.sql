-- Apply after talent-ranker's candidates, jobs, job_profile_versions, ranking_runs,
-- and ranking_results tables exist. Screening owns only the tables below.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS screening_contacts (
    candidate_id text PRIMARY KEY REFERENCES candidates(candidate_id),
    email text NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
    source text NOT NULL CHECK (length(source) BETWEEN 1 AND 100),
    source_reference text,
    contactable boolean NOT NULL DEFAULT true,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS screening_job_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text NOT NULL REFERENCES jobs(job_id),
    job_profile_version_id uuid NOT NULL REFERENCES job_profile_versions(profile_version_id),
    version integer NOT NULL CHECK (version > 0),
    questions jsonb NOT NULL CHECK (jsonb_typeof(questions) = 'object'),
    policy_version text NOT NULL DEFAULT 'screening-v1',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, version)
);

CREATE TABLE IF NOT EXISTS screening_campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text NOT NULL REFERENCES jobs(job_id),
    ranking_run_id uuid NOT NULL REFERENCES ranking_runs(run_id),
    job_profile_version_id uuid NOT NULL REFERENCES job_profile_versions(profile_version_id),
    config_id uuid NOT NULL REFERENCES screening_job_configs(id),
    config_snapshot jsonb NOT NULL CHECK (jsonb_typeof(config_snapshot) = 'object'),
    selection_rule jsonb NOT NULL CHECK (jsonb_typeof(selection_rule) = 'object'),
    proposed_candidate_ids text[] NOT NULL,
    final_candidate_ids text[],
    message_template text NOT NULL CHECK (length(message_template) BETWEEN 1 AND 20000),
    expiry_hours integer NOT NULL DEFAULT 48 CHECK (expiry_hours BETWEEN 1 AND 720),
    status text NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'approved', 'rejected')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'approved') =
        (approved_by IS NOT NULL AND approved_at IS NOT NULL AND final_candidate_ids IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS screening_campaigns_job_idx
    ON screening_campaigns (job_id, created_at DESC, id);

CREATE TABLE IF NOT EXISTS screening_invites (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id uuid NOT NULL REFERENCES screening_campaigns(id),
    candidate_id text NOT NULL REFERENCES candidates(candidate_id),
    token text NOT NULL UNIQUE CHECK (length(token) >= 32),
    status text CHECK (status IN
        ('sent', 'opened', 'started', 'completed', 'expired', 'declined')),
    sent_at timestamptz,
    opened_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    declined_at timestamptz,
    expired_at timestamptz,
    expires_at timestamptz NOT NULL,
    UNIQUE (campaign_id, candidate_id),
    CHECK (status IS NULL OR status = 'expired' OR sent_at IS NOT NULL),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
    CHECK ((status = 'declined') = (declined_at IS NOT NULL)),
    CHECK ((status = 'expired') = (expired_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS screening_invites_campaign_idx
    ON screening_invites (campaign_id, status, id);
CREATE INDEX IF NOT EXISTS screening_invites_expiry_idx
    ON screening_invites (expires_at, id)
    WHERE status IS NULL OR status IN ('sent', 'opened', 'started');

CREATE TABLE IF NOT EXISTS screening_responses (
    invite_id uuid PRIMARY KEY REFERENCES screening_invites(id),
    qualifications jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(qualifications) = 'array'),
    interest text CHECK (interest IN
        ('interested', 'not_interested', 'needs_details', 'unsure')),
    availability_status text CHECK (availability_status IN
        ('answered', 'unsure', 'prefer_not_to_answer')),
    earliest_start_date date,
    notice_status text CHECK (notice_status IN
        ('answered', 'unsure', 'prefer_not_to_answer')),
    notice_days integer CHECK (notice_days BETWEEN 0 AND 365),
    salary_status text CHECK (salary_status IN
        ('answered', 'unsure', 'prefer_not_to_answer')),
    salary_minimum numeric(16,2) CHECK (salary_minimum >= 0),
    salary_maximum numeric(16,2) CHECK (salary_maximum >= 0),
    salary_currency char(3),
    salary_period text CHECK (salary_period IN ('hour', 'month', 'year')),
    salary_negotiable boolean NOT NULL DEFAULT false,
    answer_fingerprint text CHECK (answer_fingerprint ~ '^[0-9a-f]{64}$'),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    saved_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    CHECK (salary_minimum IS NULL OR salary_maximum IS NULL
        OR salary_minimum <= salary_maximum)
);

CREATE TABLE IF NOT EXISTS screening_summary (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invite_id uuid NOT NULL UNIQUE REFERENCES screening_invites(id),
    outcome text NOT NULL CHECK (outcome IN
        ('proceed_to_interview', 'needs_recruiter_review', 'do_not_proceed')),
    confirmed jsonb NOT NULL CHECK (jsonb_typeof(confirmed) = 'array'),
    missing jsonb NOT NULL CHECK (jsonb_typeof(missing) = 'array'),
    needs_verification jsonb NOT NULL
        CHECK (jsonb_typeof(needs_verification) = 'array'),
    reason_codes jsonb NOT NULL CHECK (jsonb_typeof(reason_codes) = 'array'),
    policy_version text NOT NULL,
    config_version integer NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS screening_summary_outcome_idx
    ON screening_summary (outcome, generated_at, id);

CREATE TABLE IF NOT EXISTS screening_delivery_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invite_id uuid NOT NULL UNIQUE REFERENCES screening_invites(id),
    recipient_email text NOT NULL,
    subject text NOT NULL,
    body text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    leased_until timestamptz,
    last_error text,
    provider_receipt text,
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS screening_delivery_due_idx
    ON screening_delivery_outbox (next_attempt_at, id)
    WHERE status IN ('pending', 'failed', 'processing');

CREATE TABLE IF NOT EXISTS screening_gmail_oauth_states (
    state_hash text PRIMARY KEY,
    actor text NOT NULL,
    code_verifier text NOT NULL,
    nonce text NOT NULL,
    campaign_id uuid REFERENCES screening_campaigns(id),
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS screening_gmail_oauth_expiry_idx
    ON screening_gmail_oauth_states (expires_at);

CREATE TABLE IF NOT EXISTS screening_gmail_oauth_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    state_hash text NOT NULL,
    event text NOT NULL,
    detail text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS screening_gmail_oauth_events_created_idx
    ON screening_gmail_oauth_events (created_at);
