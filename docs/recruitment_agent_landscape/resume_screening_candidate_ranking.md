# Resume Screening & Candidate Ranking — What Works Today

**Where this fits:** This is the current resume-ranking workflow, not a working recruitment agent. It takes an approved role and indexed resumes, then returns an explainable shortlist for a recruiter. Candidate outreach and questionnaire screening are separate, later workflows.

## Follow one resume and one role

Imagine a client shares a PDF through Google Drive. The current Drive command downloads it, copies the original into our **canonical object store**, extracts the text, redacts supported contact details, separates sections such as Experience and Skills, and embeds the resulting chunks in PostgreSQL. A local PDF follows the same indexing path. The original file is stored under a candidate ID and content hash; searchable text and vectors live in the database. **S3 is the configured default for canonical storage**, but the operator must provide a bucket and working credentials. Local development can choose the filesystem instead.

Now a recruiter brings a job description. `POST /jobs/calibrate` creates a *draft* of must-have and preferred skills/requirements, experience, seniority, location, availability and compensation. By default, extraction is offline and rule-based. An opt-in LLM extractor instead makes one call for the JD, checks the returned structure and supporting quotes against the JD, and records the model and prompt version. Quote matching does not prove the model interpreted the JD correctly: the recruiter must still correct and approve a version. The ranking API refuses a draft profile. No LLM is called for each candidate.

Once the approved profile is submitted to `POST /rank`, the system does this, in order:

1. **Retrieve:** Build a query from the approved JD and priorities. Search the active resume index with BGE embeddings and PostgreSQL full-text search, once for the overall role and again for each must-have skill/requirement. Reciprocal-rank fusion (RRF) combines those candidate lists. The default retrieval limit is up to 300 candidates per branch, per query; the combined pool is not a deep assessment of every indexed resume.
2. **Rerank:** Take up to 100 candidates from that pool. The local `BAAI/bge-reranker-base` cross-encoder compares the role with retrieved resume text for each one. The assembled text is capped at 5,000 characters and the model at 512 tokens. This is the actual reranking stage; it does not run on all 9,000 resumes.
3. **Check evidence:** For those same shortlisted candidates, look through **all their indexed resume chunks**, not just the text shown to the cross-encoder. An explicit skill found in Experience or Projects can therefore count even without a Skills section. The result records a status, section, redacted passage and chunk reference for each textual requirement; available metadata is checked separately. `not_evidenced` means “not established by this data,” not “the person lacks the skill.”
4. **Score and save:** Combine the cross-encoder signal (55%), normalized retrieval signal (20%) and priority alignment (25%), then apply the current metadata quality multiplier. Sort by that score, return the requested `top_k`, and save only those returned results under a run ID. These weights are provisional ranking settings, **not calibrated probabilities or hiring decisions**.

The recruiter UI can draft and approve criteria, request a ranking, and see the returned rank, score and short explanation. The API and JSONL export hold richer structured evidence. `get_candidate_evidence` retrieves that detail for a candidate **only if they were saved in that run**.

## Where each storage provider actually stands

“S3 is our default” is true, but **default destination** and **supported client source** are different claims. The architecture document sketches more source adapters than this repository currently implements.

| Provider | Read client resumes today? | Store our canonical copy today? | Exact status |
| --- | --- | --- | --- |
| **AWS S3 / S3-compatible** | **No source adapter** | **Yes — configured default** | `S3ObjectStore` uploads through `boto3`. Set `TALENT_RANKER_CANONICAL_S3_BUCKET`; an optional endpoint supports S3-compatible services such as MinIO. No client-bucket listing/download or S3 event ingestion exists. |
| **Google Drive** | **Yes** | No | `GoogleDriveStore` uses read-only OAuth, supports file download and folder inventory/batch ingestion, then copies PDFs to the canonical store. Google Drive is **not** Google Cloud Storage. |
| **Local file / filesystem** | **Yes**, through the ingest command | **Yes**, for local development | The local canonical store implements the same write contract as S3. |
| **Google Cloud Storage (GCS)** | No | No | Not implemented. |
| **Azure Blob Storage** | No | No | Not implemented. |
| **SFTP** | No | No | Not implemented. |

The code has a `ClientStorageAdapter` contract for future read-only sources and a separate `CanonicalObjectStore` contract for our destination. A contract is an extension point, **not** evidence that AWS-source, GCS, Azure or SFTP integrations already work. The diagram in `ARCHITECTURE.md` is a target architecture on this point.

## Current interfaces and audit trail

| Need | Current interface |
| --- | --- |
| Ingest local or Drive resumes | `talent-ranker ingest`, `ingest-drive`, `ingest-drive-folder` |
| Draft, edit and approve criteria | `POST /jobs/calibrate`, `PUT /job-profiles/{id}`, `POST /job-profiles/{id}/approve` |
| Rank against an approved profile | `POST /rank` or `talent-ranker rank` |
| Inspect a saved candidate's evidence | `GET /ranking-runs/{run_id}/candidates/{candidate_id}/evidence` |
| Evaluate with recruiter labels | Offline `scripts/evaluate_ranking.py` |

PostgreSQL stores the approved profile version, calibration method/model/prompt metadata, ranking model/scoring settings, retrieval IDs, pool and shortlist sizes, and each **returned** candidate's score components, explanation and structured evidence. CSV is the compact handoff; JSONL preserves more detail. Existing databases need `db/migrations/004_requirement_evidence.sql` and `db/migrations/005_llm_calibration.sql` for the newer evidence and calibration metadata fields.

**Questions worth asking before rollout:** Did calibration capture the role correctly? How many recruiter-labelled good candidates did retrieval miss before reranking? Are the returned evidence passages actually persuasive, or just literal mentions? The evaluator can help with the first quality measurements once labels exist. There is no event-driven worker queue, OCR/malware-scan stage, per-candidate LLM call or agent orchestrator in the current implementation; those should not be described as live features.
