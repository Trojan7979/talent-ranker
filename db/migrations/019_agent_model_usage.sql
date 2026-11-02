CREATE TABLE IF NOT EXISTS agent_model_usage (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    provider text NOT NULL,
    model text NOT NULL,
    stage text NOT NULL,
    input_tokens integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL CHECK (output_tokens >= 0),
    total_tokens integer NOT NULL CHECK (total_tokens >= 0),
    cached_input_tokens integer NOT NULL DEFAULT 0 CHECK (cached_input_tokens >= 0),
    reasoning_output_tokens integer NOT NULL DEFAULT 0 CHECK (reasoning_output_tokens >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_model_usage_session_idx
    ON agent_model_usage(session_id, id);
