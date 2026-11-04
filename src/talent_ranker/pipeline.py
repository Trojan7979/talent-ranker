from __future__ import annotations

from pathlib import Path

from .access import RecruiterScope
from .calibration import build_calibrated_query
from .candidate_retrieval import retrieve_pool
from .config import Settings
from .documents import chunk_resume, document_hash, extract_resume_document
from .embeddings import HostedEmbeddingEncoder, HostedReranker
from .identifiers import validate_candidate_id
from .metadata_evidence import assess_metadata
from .privacy import redact_pii
from .ranking import RankedCandidate, evidence_snippet
from .repository import PostgresRepository
from .requirement_evidence import assess_requirements, summarize_requirements
from .scoring_policy import CandidateScoringPolicy, SemanticRelevanceScoringPolicy
from .schemas import HiringPriorities


def _candidate_document(retrieved: list[str], chunks: list[dict], limit: int = 5000) -> str:
    """Put retrieval-selected evidence first, then add remaining resume sections once."""
    passages = dict.fromkeys([
        *retrieved,
        *(chunk["content"] for chunk in chunks),
    ])
    return "\n".join(passages)[:limit]


class RankingPipeline:
    def __init__(
        self, settings: Settings, scoring_policy: CandidateScoringPolicy | None = None,
    ):
        missing = [name for name, value in (
            ("TALENT_RANKER_DATABASE_URL", settings.database_url),
            ("TALENT_RANKER_HOSTED_EMBEDDING_MODEL", settings.hosted_embedding_model),
            ("TALENT_RANKER_HOSTED_RERANKER_MODEL", settings.hosted_reranker_model),
            ("TALENT_RANKER_HOSTED_EMBEDDING_URL", settings.hosted_embedding_url),
            ("TALENT_RANKER_HOSTED_RERANKER_URL", settings.hosted_reranker_url),
        ) if not value]
        if missing:
            raise ValueError("Configure " + ", ".join(missing) + " before starting the ranking pipeline")
        self.settings = settings
        self.encoder = HostedEmbeddingEncoder(
            settings.hosted_embedding_url, settings.hosted_embedding_model,
            settings.hosted_model_timeout_seconds,
        )
        self.reranker = HostedReranker(
            settings.hosted_reranker_url, settings.hosted_reranker_model,
            settings.hosted_model_timeout_seconds,
        )
        self.repo = PostgresRepository(settings.database_url)
        self.scoring_policy = scoring_policy or SemanticRelevanceScoringPolicy()

    def ingest_resume(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
        scope: RecruiterScope | None = None,
    ) -> None:
        candidate_id = validate_candidate_id(candidate_id)
        data = path.read_bytes()
        source_hash = document_hash(data)
        source_key = (metadata or {}).get("client_source_uri") or source_uri or path.resolve().as_uri()
        if scope is not None and self.repo.has_current_embedding(
            candidate_id, source_hash, source_key, scope,
        ):
            return
        if scope is not None:
            self.repo.assert_resume_available(candidate_id, source_hash, source_key)
        extracted = extract_resume_document(path)
        index_text = redact_pii(extracted.text)
        chunks = chunk_resume(index_text, self.encoder.tokenize, self.encoder.decode)
        if not chunks:
            raise ValueError("resume has no extractable text; provide a text PDF, DOCX, or OCR")
        vectors = self.encoder.encode([chunk.embedding_text() for chunk in chunks])
        access_kwargs = {"scope": scope} if scope is not None else {}
        self.repo.upsert_candidate(
            candidate_id,
            source_uri or path.resolve().as_uri(),
            source_hash,
            index_text,
            chunks,
            vectors,
            metadata,
            links=extracted.links,
            **access_kwargs,
        )

    def ingest_pdf(
        self, candidate_id: str, path: Path, source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Preserve the original API for existing PDF callers."""
        self.ingest_resume(candidate_id, path, source_uri, metadata)

    def rank(
        self, job_id: str, job_profile: dict, top_k: int = 100,
        scope: RecruiterScope | None = None,
    ) -> tuple[str, list[RankedCandidate]]:
        if scope is None:
            raise ValueError("recruiter scope is required for ranking")
        self.repo.assert_embedding_ready(scope)
        priority_model = HiringPriorities.model_validate(job_profile["priorities"])
        jd = build_calibrated_query(job_profile["job_description"], priority_model)
        ordered, _, records, retrieval_trace = retrieve_pool(
            self.repo,
            self.encoder,
            jd,
            priority_model,
            self.settings.retrieval_limit,
            self.settings.rrf_k,
            scope,
        )
        shortlist = ordered[: self.settings.rerank_limit]
        all_chunks = self.repo.get_candidate_chunks(shortlist, scope)
        documents = [
            _candidate_document(records[cid]["chunks"], all_chunks.get(cid, []))
            for cid in shortlist
        ]
        logits = self.reranker.score(jd, documents)
        jd_terms = set(jd.lower().split())
        results = []
        for cid, doc, logit in zip(shortlist, documents, logits, strict=True):
            requirement_evidence, priority_concerns = assess_requirements(
                priority_model, all_chunks.get(cid, [])
            )
            metadata_evidence = assess_metadata(
                priority_model, records[cid]["metadata"]
            )
            requirement_evidence.extend(metadata_evidence)
            decision = self.scoring_policy.score(float(logit))
            score, components, concerns = (
                decision.score, decision.components, list(decision.concerns)
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
            {
                "embedding": self.settings.hosted_embedding_model,
                "reranker": self.settings.hosted_reranker_model,
            },
            {
                "rrf_k": self.settings.rrf_k,
                "retrieval_limit": self.settings.retrieval_limit,
                "rerank_limit": self.settings.rerank_limit,
                "retrieval_trace": retrieval_trace,
                "retrieval_pool_size": len(ordered),
                "shortlist_ids": shortlist,
                "scoring_version": "bge-semantic-relevance-v2",
                "ranking_signal": "cross_encoder_relevance",
                "retrieval_affects_score": False,
                "literal_evidence_affects_score": False,
            },
            results,
            scope,
        )
        return run_id, results
