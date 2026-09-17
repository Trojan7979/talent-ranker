from __future__ import annotations

from pathlib import Path

from .config import Settings
from .documents import chunk_resume, document_hash, extract_pdf
from .embeddings import CrossEncoderReranker, HuggingFaceEncoder
from .identifiers import validate_candidate_id
from .ranking import (
    RankedCandidate,
    build_reasoning,
    evidence_snippet,
    final_score,
    reciprocal_rank_fusion,
)
from .repository import PostgresRepository


class RankingPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.encoder = HuggingFaceEncoder(settings.embedding_model)
        self.reranker = CrossEncoderReranker(settings.reranker_model)
        self.repo = PostgresRepository(settings.database_url)

    def ingest_pdf(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        candidate_id = validate_candidate_id(candidate_id)
        data = path.read_bytes()
        text = extract_pdf(path)
        chunks = chunk_resume(text, self.encoder.tokenize, self.encoder.decode)
        vectors = self.encoder.encode([chunk.embedding_text() for chunk in chunks])
        self.repo.upsert_candidate(
            candidate_id,
            source_uri or path.resolve().as_uri(),
            document_hash(data),
            text,
            chunks,
            vectors,
            metadata,
        )

    def rank(self, job_id: str, jd: str, top_k: int = 100) -> tuple[str, list[RankedCandidate]]:
        query_vector = self.encoder.encode([jd], query=True)[0]
        dense, lexical, records = self.repo.retrieve(
            jd, query_vector, self.settings.retrieval_limit
        )
        fused = reciprocal_rank_fusion(dense, lexical, self.settings.rrf_k)
        shortlist = sorted(fused, key=lambda cid: (-fused[cid], cid))[: self.settings.rerank_limit]
        documents = ["\n".join(records[cid]["chunks"])[:5000] for cid in shortlist]
        logits = self.reranker.score(jd, documents)
        jd_terms = set(jd.lower().split())
        results = []
        for cid, doc, logit in zip(shortlist, documents, logits, strict=True):
            score, components, concerns = final_score(
                fused[cid], float(logit), records[cid]["metadata"]
            )
            evidence = [evidence_snippet(doc, jd_terms)]
            results.append(
                RankedCandidate(
                    cid,
                    score,
                    components,
                    evidence,
                    build_reasoning(evidence, concerns, score),
                )
            )
        results.sort(key=lambda r: (-r.score, r.candidate_id))
        results = results[:top_k]
        run_id = self.repo.save_run(
            job_id,
            jd,
            {"embedding": self.settings.embedding_model, "reranker": self.settings.reranker_model},
            {"rrf_k": self.settings.rrf_k, "retrieval_limit": self.settings.retrieval_limit},
            results,
        )
        return run_id, results
