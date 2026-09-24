# Talent Ranker

Production-oriented candidate ranking architecture for PDF resumes and job descriptions. The
system copies original resumes from client storage into canonical object storage, extracts and chunks resume text, embeds
chunks with Hugging Face models, retrieves candidates with hybrid search, and reranks the shortlist
with evidence-backed job-fit scoring.

Laid out the initial talent intelligence architecture using semantic search, hybrid
retrieval, and evidence-backed reranking to shortlist candidates against job requirements through
job-fit scoring.

## Local Services

```powershell
uv venv --python 3.11
uv pip install -e ".[dev]"
docker compose up -d
talent-ranker ingest CAND_0001 .\resumes\candidate-1.pdf --source-uri gdrive://FILE_ID
talent-ranker ingest-drive CAND_0002 GOOGLE_DRIVE_FILE_ID --metadata ats.json
talent-ranker drive-inventory GOOGLE_DRIVE_FOLDER_ID --output drive_inventory.csv
talent-ranker ingest-drive-folder GOOGLE_DRIVE_FOLDER_ID --manifest drive_inventory.csv
talent-ranker rank --job-id senior-ai-engineer --profile-version-id PROFILE_UUID --output .\ranking.csv
uvicorn talent_ranker.api:app --reload
python validate_submission.py .\ranking.csv
```

The first model load downloads weights from Hugging Face. Production images should pin model
revisions during the image build so runtime workers do not need public internet access. Digital PDFs
are supported directly; scanned PDFs should be routed through OCR before ingestion.

Use `uv` for the Python environment. It creates a standard `.venv`, respects `.python-version`,
and avoids accidental installs into the system interpreter. If `uv` is unavailable, use
`python -m venv .venv` and then install with `.venv\Scripts\python -m pip install -e ".[dev]"`.

For the complete database, model, API, and frontend startup sequence, see `LOCAL_RUNBOOK.md`.

Google Drive ingestion uses a personal OAuth client:

- Save the OAuth client JSON as `secrets/google-client.json`.
- Keep generated user tokens in `.tokens/drive.json`.
- Use the Drive file ID from the resume PDF URL.
- Do not commit `secrets/` or `.tokens/`.

## Architecture

```text
Client storage adapters (Drive today; S3/Azure/SFTP later)
                  |
                  v
Canonical object storage (S3 by default) -> ingestion/indexing -> Postgres/pgvector
                                                               |
Recruiter UI -> calibrate + approve hiring priorities -> FastAPI
                                                     -> hybrid retrieval
                                                     -> calibrated reranking -> ranked shortlist
                                      |
                                      v
                         get_candidate_evidence
```

- `frontend/` contains the React/Vite recruiter-facing shell.
- `src/talent_ranker/` contains the FastAPI backend, ranking pipeline, storage contracts, and domain
  logic.
- `db/schema.sql` contains the PostgreSQL and pgvector schema.
- CSV remains the benchmark handoff format, while JSONL and PostgreSQL keep richer audit data.

`GoogleDriveStore` is a client-storage adapter, not the system of record. Ingestion copies each
resume to the configured `CanonicalObjectStore`; S3 is the production default and the filesystem
implementation supports local development. Canonical resume keys are content-addressed so retries
are idempotent.

The read-only evidence tool is exposed as:

```text
GET /ranking-runs/{run_id}/candidates/{candidate_id}/evidence
```

It returns the persisted rank, score components, redacted evidence, reasoning, and job context for
that exact ranking run.

Job descriptions are calibrated before ranking. `POST /jobs/calibrate` creates an editable draft;
`PUT /job-profiles/{profile_version_id}` saves recruiter changes, and
`POST /job-profiles/{profile_version_id}/approve` freezes the approved version. `POST /rank`
requires that approved profile ID and stores it with the ranking run.

## Metadata

Use `source_platform_signals` for platform facts from LinkedIn, ATS, or another apply channel. For
LinkedIn specifically, store them as:

```json
{
  "source_platform_signals": {
    "linkedin": {
      "recruiter_response_rate": 0.42,
      "last_active_days": 12,
      "open_to_work": true
    }
  }
}
```

These signals should adjust confidence and availability only. The primary score should still come
from job description alignment and resume evidence.

## Pilot Scale

The initial operating scope is 9,000 candidates. External candidate IDs are one-based and use four
digits, from `CAND_0001` through `CAND_9000`. The database keeps the identifier as text so the
public format can evolve without changing storage relationships.

The recruiter UI will review ranked results in pages of up to 1,000. Pagination is a presentation
and API concern; it does not encode a page or batch number in the candidate ID. Production API
pagination should use a stable ranking cursor rather than loading all 9,000 records in the browser.
