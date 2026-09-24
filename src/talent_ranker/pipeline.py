from __future__ import annotations

from pathlib import Path

from .calibration import build_calibrated_query
from .candidate_retrieval import retrieve_pool
from .config import Settings
from .documents import chunk_resume, document_hash, extract_pdf
from .embeddings import CrossEncoderReranker, HuggingFaceEncoder
from .identifiers import validate_candidate_id
from .metadata_evidence import assess_metadata
from .privacy import redact_pii
from .ranking import (
    RankedCandidate,
    evidence_snippet,
    final_score,
)
from .repository import PostgresRepository
from .requirement_evidence import assess_requirements, summarize_requirements
from .schemas import HiringPriorities


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
        extracted_text = extract_pdf(path)
        index_text = redact_pii(extracted_text)
        chunks = chunk_resume(index_text, self.encoder.tokenize, self.encoder.decode)
        vectors = self.encoder.encode([chunk.embedding_text() for chunk in chunks])
        self.repo.upsert_candidate(
            candidate_id,
            source_uri or path.resolve().as_uri(),
            document_hash(data),
            index_text,
            chunks,
            vectors,
            metadata,
        )

    def rank(
        self, job_id: str, job_profile: dict, top_k: int = 100
    ) -> tuple[str, list[RankedCandidate]]:
        priority_model = HiringPriorities.model_validate(job_profile["priorities"])
        jd = build_calibrated_query(job_profile["job_description"], priority_model)
        ordered, fused, records, retrieval_trace = retrieve_pool(
            self.repo,
            self.encoder,
            jd,
            priority_model,
            self.settings.retrieval_limit,
            self.settings.rrf_k,
        )
        shortlist = ordered[: self.settings.rerank_limit]
        all_chunks = self.repo.get_candidate_chunks(shortlist)
        documents = ["\n".join(records[cid]["chunks"])[:5000] for cid in shortlist]
        logits = self.reranker.score(jd, documents)
        jd_terms = set(jd.lower().split())
        results = []
        for cid, doc, logit in zip(shortlist, documents, logits, strict=True):
            requirement_evidence, priority_score, priority_concerns = assess_requirements(
                priority_model, all_chunks.get(cid, [])
            )
            metadata_evidence, metadata_earned, metadata_possible = assess_metadata(
                priority_model, records[cid]["metadata"]
            )
            textual_count = len(requirement_evidence)
            requirement_evidence.extend(metadata_evidence)
            if metadata_possible:
                priority_score = (priority_score * textual_count + metadata_earned) / (
                    textual_count + metadata_possible
                )
            score, components, concerns = final_score(
                fused[cid],
                float(logit),
                records[cid]["metadata"],
                priority_score,
            )
            concerns.extend(priority_concerns)
            supported = [item["passage"] for item in requirement_evidence if item.get("passage")]
            evidence = supported[:3] or [evidence_snippet(doc, jd_terms)]
            results.append(
                RankedCandidate(
                    cid,
                    score,
                    components,
                    evidence,
                    summarize_requirements(requirement_evidence, concerns),
                    requirement_evidence,
                )
            )
        results.sort(key=lambda r: (-r.score, r.candidate_id))
        results = results[:top_k]
        run_id = self.repo.save_run(
            job_id,
            job_profile["profile_version_id"],
            jd,
            {"embedding": self.settings.embedding_model, "reranker": self.settings.reranker_model},
            {
                "rrf_k": self.settings.rrf_k,
                "retrieval_limit": self.settings.retrieval_limit,
                "rerank_limit": self.settings.rerank_limit,
                "retrieval_trace": retrieval_trace,
                "retrieval_pool_size": len(ordered),
                "shortlist_ids": shortlist,
                "scoring_version": "requirement-evidence-v1",
                "score_weights": {
                    "semantic": 0.55,
                    "retrieval": 0.20,
                    "calibrated_priority": 0.25,
                },
            },
            results,
        )
        return run_id, results
