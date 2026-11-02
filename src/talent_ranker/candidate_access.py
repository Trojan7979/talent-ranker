"""Source-linked candidate grants shared by retrieval and recruiter APIs."""

from collections.abc import Sequence

from .access import RecruiterScope


class CandidateAccessRepositoryMixin:
    def accessible_candidate_ids(
        self, candidate_ids: Sequence[str], scope: RecruiterScope
    ) -> set[str]:
        if not candidate_ids:
            return set()
        rows = self.conn.execute(
            """SELECT c.candidate_id FROM candidates c
               JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                 AND g.workspace_id=%s AND g.actor_id=%s
                 AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
               WHERE c.deleted_at IS NULL AND c.candidate_id=ANY(%s)""",
            (scope.workspace_id, scope.actor_id, list(candidate_ids)),
        ).fetchall()
        return {row[0] for row in rows}
