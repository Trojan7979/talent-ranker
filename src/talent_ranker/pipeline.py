from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path

from .access import RecruiterScope
from .batch_ingestion import IngestionOutcome
from .calibration import build_calibrated_query
from .candidate_retrieval import retrieve_pool
from .config import Settings
from .criterion_matching import approved_criteria, match_criteria
from .documents import chunk_resume, document_hash, extract_resume_document
from .embeddings import HostedEmbeddingEncoder, HostedReranker
from .evidence_assessment import EvidenceAssessmentError, EvidenceAssessor, summarize_evidence
from .identifiers import validate_candidate_id
from .metadata_evidence import assess_metadata
from .privacy import redact_pii
from .ranking import RankedCandidate
from .ranking_explanations import RankingExplanationGenerator
from .repository import PostgresRepository
from .schemas import HiringPriorities
from .scoring_policy import CriterionRelevanceScoringPolicy
from .source_eligibility import document_kind

logger = logging.getLogger(__name__)


class RankingPipeline:
    def __init__(
        self, settings: Settings, scoring_policy: CriterionRelevanceScoringPolicy | None = None,
        explanation_generator: RankingExplanationGenerator | None = None,
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
        self.scoring_policy = scoring_policy or CriterionRelevanceScoringPolicy()
        self.explanation_generator = explanation_generator

    def _assessor(self) -> EvidenceAssessor:
        existing = getattr(self, "evidence_assessor", None)
        if existing is not None:
            return existing
        key = getattr(self.settings, "calibration_api_key", None)
        assessor = EvidenceAssessor(
            self.settings.calibration_api_url,
            key.get_secret_value() if key else "",
            self.settings.calibration_model,
            self.settings.calibration_timeout_seconds,
        )
        self.evidence_assessor = assessor
        return assessor

    def ingest_resume(
        self,
        candidate_id: str,
        path: Path,
        source_uri: str | None = None,
        metadata: dict | None = None,
        scope: RecruiterScope | None = None,
    ) -> IngestionOutcome:
        candidate_id = validate_candidate_id(candidate_id)
        data = path.read_bytes()
        source_hash = document_hash(data)
        source_key = (metadata or {}).get("client_source_uri") or source_uri or path.resolve().as_uri()
        if scope is not None and self.repo.has_current_embedding(
            candidate_id, source_hash, source_key, scope,
        ):
            return IngestionOutcome.UNCHANGED
        if scope is not None:
            self.repo.assert_resume_available(candidate_id, source_hash, source_key)
        extracted = extract_resume_document(path)
        index_text = redact_pii(extracted.text)
        stored_metadata = {**(metadata or {}), "document_kind": document_kind(index_text)}
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
            stored_metadata,
            links=extracted.links,
            **access_kwargs,
        )
        return IngestionOutcome.EMBEDDED

    def ingest_pdf(
        self, candidate_id: str, path: Path, source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> IngestionOutcome:
        """Preserve the original API for existing PDF callers."""
        return self.ingest_resume(candidate_id, path, source_uri, metadata)

    def rank(
        self, job_id: str, job_profile: dict, top_k: int = 100,
        scope: RecruiterScope | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[str, list[RankedCandidate]]:
        progress = progress or (lambda _: None)
        if scope is None:
            raise ValueError("recruiter scope is required for ranking")
        self.repo.assert_embedding_ready(scope)
        priority_model = HiringPriorities.model_validate(job_profile["priorities"])
        criteria = approved_criteria(priority_model)
        if not criteria:
            raise ValueError("approved job profile has no rankable qualifications")
        jd = build_calibrated_query(job_profile["job_description"], priority_model)
        progress("Search: retrieving candidates from indexed resumes")
        logger.info("Retrieving candidates using %s JD criteria.", len(criteria))
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
        logger.info(
            "Retrieval complete: %s candidates found; %s entering BGE reranking.",
            len(ordered), len(shortlist),
        )
        progress(f"Search: found {len(ordered)} candidates; reranker checking {len(shortlist)}")
        all_chunks = self.repo.get_candidate_chunks(shortlist, scope)
        matches = match_criteria(criteria, all_chunks, self.encoder, self.reranker)
        ranked = []
        for cid in shortlist:
            decision = self.scoring_policy.score(matches.get(cid, []))
            ranked.append((cid, decision))
        ranked.sort(key=lambda row: (
            -row[1].components.get("must_have_relevance", 0),
            -row[1].components.get("preferred_relevance", 0),
            -row[1].components.get("role_relevance", 0), row[0],
        ))
        selected = ranked[:top_k]
        logger.info("BGE reranking complete: %s candidates selected for evidence review.", len(selected))
        progress(f"Reranker: selected {len(selected)} candidates; evidence model checking citations")
        assessments = {}
        if selected:
            logger.info("Assessing cited resume evidence for %s candidates.", len(selected))
            try:
                assessor = self._assessor()
            except EvidenceAssessmentError as error:
                logger.warning("Evidence assessor unavailable: %s", error)
                assessments = {cid: [] for cid, _ in selected}
            else:
                def assess_candidate(row):
                    candidate_id = row[0]
                    try:
                        return candidate_id, assessor.assess(matches[candidate_id])
                    except EvidenceAssessmentError as error:
                        logger.warning(
                            "Evidence assessment unavailable for candidate %s: %s (%s)",
                            candidate_id, error, error.__cause__,
                        )
                        return candidate_id, []
                with ThreadPoolExecutor(max_workers=min(4, len(selected))) as executor:
                    assessments = dict(executor.map(assess_candidate, selected))
            logger.info("Cited resume evidence assessed for %s candidates.", len(assessments))
        results = []
        explanations = {}
        generator = getattr(self, "explanation_generator", None)
        if generator and selected:
            progress("Explanation model: preparing cited candidate bullets")
            logger.info("Preparing concise candidate explanations.")
            with ThreadPoolExecutor(max_workers=min(4, len(selected))) as executor:
                explanations = dict(executor.map(
                    lambda row: (row[0], generator.explain(assessments[row[0]])), selected,
                ))
            logger.info("Candidate explanations prepared for %s results.",
                        sum(bool(value) for value in explanations.values()))
        for cid, decision in selected:
            assessment_unavailable = not assessments[cid]
            requirement_evidence = list(assessments[cid])
            requirement_evidence.extend(assess_metadata(priority_model, records[cid]["metadata"]))
            evidence = [item["passage"] for item in requirement_evidence
                        if item.get("passage") and item["status"] in {"supported", "partial"}]
            results.append(RankedCandidate(
                cid, decision.score, decision.components, evidence[:3],
                explanations.get(cid) or (
                    "Evidence assessment was unavailable; review the resume."
                    if assessment_unavailable else summarize_evidence(requirement_evidence)
                ), requirement_evidence,
            ))
        progress(f"Storage: saving {len(results)} ranked candidates")
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
                "scoring_version": "criterion-passage-bge-v1",
                "ranking_signal": "criterion_passage_relevance",
                "evidence_assessment": "grounded_model_shadow",
                "retrieval_affects_score": False,
                "literal_evidence_affects_score": False,
                "model_evidence_affects_score": False,
                "experience_years_affect_score": False,
            },
            results,
            scope,
        )
        return run_id, results
