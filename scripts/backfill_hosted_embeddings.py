"""Fill the hosted embedding column from already-redacted resume chunks."""

from __future__ import annotations

import argparse

from talent_ranker.config import SETTINGS
from talent_ranker.documents import Chunk
from talent_ranker.embeddings import HostedEmbeddingEncoder
from talent_ranker.repository import PostgresRepository, _vector


def backfill(batch_size: int) -> int:
    encoder = HostedEmbeddingEncoder(
        SETTINGS.hosted_embedding_url,
        SETTINGS.hosted_embedding_model,
        SETTINGS.hosted_model_timeout_seconds,
    )
    repo = PostgresRepository(SETTINGS.database_url)
    filled = 0
    try:
        while True:
            rows = repo.conn.execute(
                """SELECT rc.chunk_id, rc.section, rc.content, rc.chunk_metadata
                   FROM resume_chunks rc
                   JOIN candidates c ON c.candidate_id = rc.candidate_id
                   WHERE c.deleted_at IS NULL AND rc.embedding_v2 IS NULL
                   ORDER BY rc.chunk_id LIMIT %s""",
                (batch_size,),
            ).fetchall()
            if not rows:
                repo.assert_embedding_ready()
                return filled
            texts = [
                Chunk(0, 0, section, content, "", metadata).embedding_text()
                for _, section, content, metadata in rows
            ]
            vectors = encoder.encode(texts)
            with repo.conn.transaction(), repo.conn.cursor() as cur:
                cur.executemany(
                    """UPDATE resume_chunks SET embedding_v2 = %s::vector
                       WHERE chunk_id = %s AND embedding_v2 IS NULL""",
                    [(_vector(vector), row[0]) for row, vector in zip(rows, vectors, strict=True)],
                )
            filled += len(rows)
            print(f"filled {filled} hosted embeddings", flush=True)
    finally:
        repo.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 64:
        parser.error("batch size must be between 1 and 64")
    print(f"complete: {backfill(args.batch_size)} chunks updated")


if __name__ == "__main__":
    main()
