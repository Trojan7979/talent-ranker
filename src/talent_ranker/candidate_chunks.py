from __future__ import annotations

from collections.abc import Sequence


class CandidateChunksRepositoryMixin:
    def get_candidate_chunks(self, candidate_ids: Sequence[str]) -> dict[str, list[dict]]:
        """Return every indexed section for shortlisted active candidates in resume order."""
        if not candidate_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT rc.candidate_id, rc.ordinal, rc.section, rc.content,
                          c.source_sha256
                   FROM resume_chunks rc
                   JOIN candidates c ON c.candidate_id = rc.candidate_id
                   WHERE rc.candidate_id = ANY(%s) AND c.deleted_at IS NULL
                   ORDER BY rc.candidate_id, rc.ordinal""",
                (list(candidate_ids),),
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
