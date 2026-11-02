from __future__ import annotations

from collections.abc import Sequence

from .access import RecruiterScope


class CandidateChunksRepositoryMixin:
    def assert_resume_available(self, candidate_id: str, source_hash: str,
                                source_uri: str) -> None:
        """Reject stale intake mappings before paying for embedding inference."""
        duplicate = self.conn.execute(
            """SELECT 1 FROM candidates WHERE source_sha256=%s
                 AND candidate_id<>%s AND deleted_at IS NULL
               UNION ALL
               SELECT 1 FROM sharepoint_candidate_files WHERE source_uri=%s
                 AND candidate_id<>%s LIMIT 1""",
            (source_hash, candidate_id, source_uri, candidate_id),
        ).fetchone()
        if duplicate:
            raise ValueError("resume was already indexed under another candidate; analyze the source again")

    def has_current_embedding(
        self, candidate_id: str, source_hash: str, source_uri: str,
        scope: RecruiterScope,
    ) -> bool:
        """An unchanged owned resume with complete hosted vectors needs no new inference."""
        return bool(self.conn.execute(
            """SELECT 1 FROM candidates c
               JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                 AND g.workspace_id=%s AND g.actor_id=%s AND g.grant_kind='owner'
                 AND g.source_uri=%s
               WHERE c.candidate_id=%s AND c.source_sha256=%s
                 AND c.deleted_at IS NULL
                 AND EXISTS (SELECT 1 FROM resume_chunks rc
                             WHERE rc.candidate_id=c.candidate_id)
                 AND NOT EXISTS (SELECT 1 FROM resume_chunks rc
                                 WHERE rc.candidate_id=c.candidate_id
                                   AND rc.embedding_v2 IS NULL)""",
            (scope.workspace_id, scope.actor_id, source_uri,
             candidate_id, source_hash),
        ).fetchone())

    def assert_embedding_ready(self, scope: RecruiterScope) -> None:
        """Prevent a model switch from silently excluding indexed candidates."""
        unindexed = self.conn.execute(
            """SELECT count(*) FROM candidates c
               JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                 AND g.workspace_id=%s AND g.actor_id=%s
                 AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
               WHERE c.deleted_at IS NULL AND NOT EXISTS (
                   SELECT 1 FROM resume_chunks rc WHERE rc.candidate_id=c.candidate_id
               )""",
            (scope.workspace_id, scope.actor_id),
        ).fetchone()[0]
        if unindexed:
            raise RuntimeError(f"{unindexed} resumes have no indexed chunks")
        missing = self.conn.execute(
            """SELECT count(*) FROM resume_chunks rc
               JOIN candidates c ON c.candidate_id = rc.candidate_id
               JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                 AND g.workspace_id=%s AND g.actor_id=%s
                 AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
               WHERE c.deleted_at IS NULL AND rc.embedding_v2 IS NULL""",
            (scope.workspace_id, scope.actor_id),
        ).fetchone()[0]
        if missing:
            raise RuntimeError(f"{missing} resume chunks need hosted embedding backfill")

    def get_candidate_chunks(
        self, candidate_ids: Sequence[str], scope: RecruiterScope
    ) -> dict[str, list[dict]]:
        """Return every indexed section for shortlisted active candidates in resume order."""
        if not candidate_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT rc.candidate_id, rc.ordinal, rc.section, rc.content,
                          c.source_sha256
                   FROM resume_chunks rc
                   JOIN candidates c ON c.candidate_id = rc.candidate_id
                   JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                     AND g.workspace_id=%s AND g.actor_id=%s
                     AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                   WHERE rc.candidate_id = ANY(%s) AND c.deleted_at IS NULL
                   ORDER BY rc.candidate_id, rc.ordinal""",
                (scope.workspace_id, scope.actor_id, list(candidate_ids)),
            )
            rows = cur.fetchall()
        chunks: dict[str, list[dict]] = {candidate_id: [] for candidate_id in candidate_ids}
        for candidate_id, ordinal, section, content, source_hash in rows:
            chunks[candidate_id].append(
                {
                    "ordinal": ordinal,
                    "section": section,
                    "content": content,
                    "source_sha256": source_hash,
                }
            )
        return chunks
