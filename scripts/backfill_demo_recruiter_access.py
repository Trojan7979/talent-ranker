"""Assign pre-isolation demo data to the one configured local recruiter."""

from pathlib import Path

import psycopg
from candidate_screening.config import Settings as ScreeningSettings

from sieve_app.agent_config import AgentSettings
from talent_ranker.config import SETTINGS


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    screening = ScreeningSettings(
        _env_file=[root / "candidate-screening" / ".env", root / ".env"]
    )
    agent = AgentSettings(_env_file=root / ".env")
    actors = set(screening.recruiter_tokens.values())
    if agent.workspace_id != "demo" or len(actors) != 1:
        raise SystemExit("legacy backfill is only for the single-recruiter demo workspace")
    actor = actors.pop()
    if actor not in agent.allowed_jobs_by_actor:
        raise SystemExit("configured demo recruiter has no assigned jobs")

    with psycopg.connect(SETTINGS.database_url) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM candidate_source_grants")
        if cur.fetchone()[0]:
            raise SystemExit("candidate grants already exist; review ownership before backfill")
        cur.execute("SELECT count(*) FROM ranking_runs WHERE workspace_id IS NOT NULL OR actor_id IS NOT NULL")
        if cur.fetchone()[0]:
            raise SystemExit("owned ranking runs already exist; review ownership before backfill")
        cur.execute(
            """INSERT INTO candidate_source_grants
               (candidate_id,workspace_id,actor_id,source_uri,grant_kind)
               SELECT candidate_id,%s,%s,
                      coalesce(nullif(metadata->>'client_source_uri',''),source_uri),'owner'
               FROM candidates WHERE deleted_at IS NULL""",
            (agent.workspace_id, actor),
        )
        candidates = cur.rowcount
        cur.execute(
            "UPDATE ranking_runs SET workspace_id=%s,actor_id=%s",
            (agent.workspace_id, actor),
        )
        runs = cur.rowcount
    print(f"Assigned {candidates} candidates and {runs} historical runs to {actor} in {agent.workspace_id}.")


if __name__ == "__main__":
    main()
