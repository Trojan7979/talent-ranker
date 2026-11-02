"""Normalize provider-reported token counts and persist them per chat session."""

from collections.abc import Mapping


def normalize_usage(raw: Mapping | None) -> dict[str, int] | None:
    if not isinstance(raw, Mapping):
        return None
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens"))
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens"))
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    if input_tokens < 0 or output_tokens < 0:
        return None
    details_in = raw.get("input_token_details") or raw.get("prompt_tokens_details") or {}
    details_out = raw.get("output_token_details") or raw.get("completion_tokens_details") or {}
    cached = details_in.get("cache_read", details_in.get("cached_tokens", 0))
    reasoning = details_out.get("reasoning", details_out.get("reasoning_tokens", 0))
    total = raw.get("total_tokens")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total if isinstance(total, int) and total >= 0 else input_tokens + output_tokens,
        "cached_input_tokens": cached if isinstance(cached, int) and cached >= 0 else 0,
        "reasoning_output_tokens": reasoning if isinstance(reasoning, int) and reasoning >= 0 else 0,
    }


class AgentModelUsageMixin:
    def record_model_usage(
        self, session_id, provider: str, model: str, stage: str,
        raw_usage: Mapping | None,
    ) -> bool:
        usage = normalize_usage(raw_usage)
        if usage is None:
            return False
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_model_usage
                   (session_id,provider,model,stage,input_tokens,output_tokens,
                    total_tokens,cached_input_tokens,reasoning_output_tokens)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session_id, provider, model, stage, *usage.values()),
            )
        return True

    def model_usage_summary(self, session_id) -> dict:
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT provider,model,stage,count(*) AS calls,
                          sum(input_tokens) AS input_tokens,
                          sum(output_tokens) AS output_tokens,
                          sum(total_tokens) AS total_tokens,
                          sum(cached_input_tokens) AS cached_input_tokens,
                          sum(reasoning_output_tokens) AS reasoning_output_tokens
                   FROM agent_model_usage WHERE session_id=%s
                   GROUP BY provider,model,stage ORDER BY provider,model,stage""",
                (session_id,),
            )
            rows = cur.fetchall()
        items = [dict(row) for row in rows]
        return {
            "session_id": str(session_id),
            "models": items,
            "totals": {
                key: sum(item[key] for item in items)
                for key in ("calls", "input_tokens", "output_tokens", "total_tokens")
            },
        }
