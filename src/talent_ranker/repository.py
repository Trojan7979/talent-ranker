from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

from .candidate_chunks import CandidateChunksRepositoryMixin
from .documents import Chunk
from .job_profiles import JobProfileRepositoryMixin


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


class PostgresRepository(CandidateChunksRepositoryMixin, JobProfileRepositoryMixin):
    def __init__(self, database_url: str):
        import psycopg

        self.conn = psycopg.connect(database_url)

    def close(self) -> None:
        self.conn.close()

    def iter_privacy_texts(self) -> Iterator[tuple[str, str, str]]:
        """Stream auditable text fields without loading the database into memory."""
        query = """SELECT candidate_id, field, content
                   FROM (
                     SELECT candidate_id, 'candidates.raw_text' field, raw_text content
                     FROM candidates
                     UNION ALL
                     SELECT candidate_id, 'resume_chunks.content', content
                     FROM resume_chunks
                     UNION ALL
                     SELECT candidate_id, 'resume_chunks.parent_content', parent_content
                     FROM resume_chunks
                     UNION ALL
                     SELECT candidate_id, 'ranking_results.evidence', evidence::text
                     FROM ranking_results
                     UNION ALL
                     SELECT candidate_id, 'ranking_results.requirement_evidence',
                            requirement_evidence::text
                     FROM ranking_results
                     UNION ALL
                     SELECT candidate_id, 'ranking_results.reasoning', reasoning
                     FROM ranking_results
                   ) privacy_texts
                   ORDER BY candidate_id, field"""
        with self.conn.cursor(name="privacy_audit") as cur:
            cur.execute(query)
            yield from cur

    def upsert_candidate(
        self,
        candidate_id: str,
        source_uri: str,
        source_sha256: str,
        raw_text: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        metadata: dict | None = None,
    ) -> None:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO candidates(candidate_id, source_uri, source_sha256, raw_text, metadata)
                   VALUES (%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT(candidate_id) DO UPDATE SET source_uri=excluded.source_uri,
                     source_sha256=excluded.source_sha256, raw_text=excluded.raw_text,
                     metadata=excluded.metadata, deleted_at=NULL""",
                (candidate_id, source_uri, source_sha256, raw_text, json.dumps(metadata or {})),
            )
            cur.execute("DELETE FROM resume_chunks WHERE candidate_id=%s", (candidate_id,))
            cur.executemany(
                """INSERT INTO resume_chunks
                   (candidate_id,ordinal,parent_ordinal,section,content,parent_content,
                    chunk_metadata,embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)""",
                [
                    (
                        candidate_id,
                        c.ordinal,
                        c.parent_ordinal,
                        c.section,
                        c.content,
                        c.parent_content,
                        json.dumps(c.metadata),
                        _vector(e),
                    )
                    for c, e in zip(chunks, embeddings, strict=True)
                ],
            )

    def retrieve(
        self, jd: str, embedding: Sequence[float], limit: int
    ) -> tuple[list[str], list[str], dict]:
        """Return candidate-level dense/lexical ranks plus their strongest chunks."""
        query = "plainto_tsquery('english', %s)"
        with self.conn.cursor() as cur:
            cur.execute(
                """WITH nearest_chunks AS (
                       SELECT rc.candidate_id, rc.parent_content AS content,
                         1-(rc.embedding <=> %s::vector) similarity
                       FROM resume_chunks rc
                       JOIN candidates c ON c.candidate_id = rc.candidate_id
                       WHERE c.deleted_at IS NULL
                       ORDER BY rc.embedding <=> %s::vector, rc.candidate_id, rc.ordinal
                       LIMIT %s
                   ), best_per_candidate AS (
                       SELECT DISTINCT ON (candidate_id) candidate_id, content, similarity
                       FROM nearest_chunks ORDER BY candidate_id, similarity DESC, content
                   )
                   SELECT candidate_id, content, similarity FROM best_per_candidate
                   ORDER BY similarity DESC, candidate_id LIMIT %s""",
                (_vector(embedding), _vector(embedding), limit * 3, limit),
            )
            dense_rows = sorted(cur.fetchall(), key=lambda row: row[2], reverse=True)[:limit]
            cur.execute(
                f"""SELECT rc.candidate_id, rc.parent_content,
                            ts_rank_cd(rc.content_tsv, {query}) score
                     FROM resume_chunks rc
                     JOIN candidates c ON c.candidate_id = rc.candidate_id
                     WHERE c.deleted_at IS NULL AND rc.content_tsv @@ {query}
                     ORDER BY score DESC, rc.candidate_id, rc.ordinal LIMIT %s""",
                (jd, jd, limit * 3),
            )
            lexical_rows = cur.fetchall()
        lexical_ids, lexical_chunks, seen = [], {}, set()
        for cid, content, _ in lexical_rows:
            lexical_chunks.setdefault(cid, []).append(content)
            if cid not in seen:
                seen.add(cid)
                lexical_ids.append(cid)
            if len(lexical_ids) >= limit:
                break
        dense_ids = [row[0] for row in dense_rows]
        chunks = {row[0]: [row[1]] for row in dense_rows}
        for cid, values in lexical_chunks.items():
            chunks.setdefault(cid, []).extend(values[:2])
        selected_ids = list(dict.fromkeys(dense_ids + lexical_ids))
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT candidate_id, metadata
                   FROM candidates
                   WHERE deleted_at IS NULL AND candidate_id = ANY(%s)""",
                (selected_ids,),
            )
            candidate_rows = {row[0]: {"metadata": row[1]} for row in cur.fetchall()}
        return (
            dense_ids,
            lexical_ids,
            {
                cid: {**candidate_rows[cid], "chunks": chunks.get(cid, [])}
                for cid in selected_ids
                if cid in candidate_rows
            },
        )

    def get_candidate_evidence(self, run_id: str, candidate_id: str) -> dict | None:
        """Return the persisted evidence for one candidate in one ranking run."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT rr.run_id, r.job_id, rr.candidate_id, rr.rank, rr.score,
                          rr.score_components, rr.evidence, rr.reasoning, r.created_at,
                          r.job_profile_version_id, rr.requirement_evidence
                   FROM ranking_results rr
                   JOIN ranking_runs r ON r.run_id = rr.run_id
                   JOIN candidates c ON c.candidate_id = rr.candidate_id
                   WHERE rr.run_id = %s::uuid AND rr.candidate_id = %s
                     AND c.deleted_at IS NULL""",
                (run_id, candidate_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row[0]),
            "job_id": row[1],
            "candidate_id": row[2],
            "rank": row[3],
            "score": row[4],
            "score_components": row[5],
            "evidence": row[6],
            "reasoning": row[7],
            "created_at": row[8],
            "job_profile_version_id": str(row[9]) if row[9] else None,
            "requirement_evidence": row[10],
        }

    def save_run(
        self,
        job_id: str,
        profile_version_id: str,
        jd: str,
        models: dict,
        config: dict,
        results: Sequence,
    ) -> str:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ranking_runs
                   (job_id,job_profile_version_id,jd_text,model_versions,scoring_config)
                   VALUES (%s,%s::uuid,%s,%s::jsonb,%s::jsonb) RETURNING run_id""",
                (
                    job_id,
                    profile_version_id,
                    jd,
                    json.dumps(models),
                    json.dumps(config),
                ),
            )
            run_id = str(cur.fetchone()[0])
            cur.executemany(
                """INSERT INTO ranking_results
                   (run_id,candidate_id,rank,score,score_components,evidence,reasoning,
                    requirement_evidence)
                   VALUES (%s::uuid,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb)""",
                [
                    (
                        run_id,
                        r.candidate_id,
                        rank,
                        r.score,
                        json.dumps(r.components),
                        json.dumps(r.evidence),
                        r.reasoning,
                        json.dumps(r.requirement_evidence),
                    )
                    for rank, r in enumerate(results, 1)
                ],
            )
        return run_id
