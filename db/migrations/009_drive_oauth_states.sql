CREATE TABLE IF NOT EXISTS drive_oauth_states (
    state_hash text PRIMARY KEY,
    actor text NOT NULL,
    code_verifier text NOT NULL,
    nonce text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS drive_oauth_states_expiry_idx
  ON drive_oauth_states(expires_at);
