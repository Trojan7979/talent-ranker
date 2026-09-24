# Local Development Runbook

This runbook starts PostgreSQL/pgvector in Docker and runs the API, Hugging Face models, and
frontend as local processes.

## 1. Activate And Refresh The Environment

```powershell
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

The second command is required after dependencies in `pyproject.toml` change.

## 2. Check Local Configuration

```powershell
Get-Content .env
```

The local defaults should point to PostgreSQL on `localhost:5432` and allow the Vite origins
`http://localhost:5173` and `http://127.0.0.1:5173`.

Production defaults to S3 canonical storage. For local development without S3, add:

```text
TALENT_RANKER_CANONICAL_STORAGE_BACKEND=filesystem
TALENT_RANKER_CANONICAL_LOCAL_ROOT=.data/object-storage
```

For production, keep `s3` and set `TALENT_RANKER_CANONICAL_S3_BUCKET`. Google Drive is an input
adapter; every downloaded resume is copied to canonical storage before it is indexed.

## 3. Start PostgreSQL And pgvector

Make sure Docker Desktop is running, then execute:

```powershell
docker compose config
docker compose up -d
docker compose ps
```

For a fresh Docker volume, `db/schema.sql` runs automatically. If the volume existed before the
parent-child chunking change, apply the migration once:

```powershell
Get-Content db\migrations\002_parent_child_chunks.sql |
  docker compose exec -T postgres psql -U talent_ranker -d talent_ranker
```

Apply the job-calibration migration to an existing volume as well:

```powershell
Get-Content db\migrations\003_job_calibration.sql |
  docker compose exec -T postgres psql -U talent_ranker -d talent_ranker
```

Then apply the evidence and LLM-calibration metadata migrations to existing volumes:

```powershell
Get-Content db\migrations\004_requirement_evidence.sql |
  docker compose exec -T postgres psql -U talent_ranker -d talent_ranker
Get-Content db\migrations\005_llm_calibration.sql |
  docker compose exec -T postgres psql -U talent_ranker -d talent_ranker
```

Verify the extensions and tables:

```powershell
docker compose exec postgres psql -U talent_ranker -d talent_ranker -c "\dx"
docker compose exec postgres psql -U talent_ranker -d talent_ranker -c "\dt"
docker compose exec postgres psql -U talent_ranker -d talent_ranker -c "\d resume_chunks"
```

## 4. Download The Local Models

No external inference API key is required for local embedding and reranking. This command downloads
and caches both Hugging Face models on the first run:

```powershell
python -c "from talent_ranker.config import SETTINGS; from talent_ranker.embeddings import HuggingFaceEncoder, CrossEncoderReranker; HuggingFaceEncoder(SETTINGS.embedding_model).model; CrossEncoderReranker(SETTINGS.reranker_model).model; print('models ready')"
```

The configured models are:

- `BAAI/bge-small-en-v1.5` for 384-dimensional normalized embeddings.
- `BAAI/bge-reranker-base` for cross-encoder reranking.

JD calibration defaults to the offline rule-based extractor. To opt into one LLM call per new
calibration draft, set these in `.env` and restart the API:

```text
TALENT_RANKER_CALIBRATION_EXTRACTOR=llm
TALENT_RANKER_CALIBRATION_MODEL=deepseek-ai/DeepSeek-V4-Pro
TALENT_RANKER_CALIBRATION_API_KEY=<your Qubrid API key>
```

The job description is sent to the configured calibration endpoint; resumes are not. A failed or
ungrounded model response returns an error, not a silently incomplete draft. Recruiter review and
approval remain mandatory before ranking. The API key is not needed for ranking itself.

## 5. Ingest And Embed A Resume

Place a digital PDF in the ignored `resumes` directory and ingest it:

```powershell
New-Item -ItemType Directory -Force resumes
talent-ranker ingest CAND_0001 .\resumes\candidate-1.pdf
```

The command extracts text, detects evidence sections, creates token-aware child chunks, generates
embeddings, and writes the candidate and chunks to PostgreSQL. A scanned image-only PDF must pass
through OCR first.

## 6. Bulk Ingestion From A Google Drive Folder

Copy the folder ID from a Drive folder URL such as:

```text
https://drive.google.com/drive/folders/FOLDER_ID
```

Export an inventory of every PDF directly inside that folder:

```powershell
talent-ranker drive-inventory FOLDER_ID --output .\drive_inventory.csv
```

Open `drive_inventory.csv` and fill the `candidate_id` column from the ATS or application source.
Leave any row blank to skip that file. Do not change `drive_file_id`.

```csv
candidate_id,drive_file_id,file_name,modified_time,md5_checksum,size_bytes,metadata_json
CAND_0001,DRIVE_FILE_ID_1,candidate-one.pdf,2026-09-17T10:00:00Z,,,{}
CAND_0002,DRIVE_FILE_ID_2,candidate-two.pdf,2026-09-17T10:05:00Z,,,{}
```

Run the batch:

```powershell
talent-ranker ingest-drive-folder FOLDER_ID --manifest .\drive_inventory.csv
```

The command lists the folder again, verifies each manifest file belongs to it, and processes files
sequentially so one resume does not consume memory indefinitely. Individual failures are reported
without discarding successful candidates. Generated manifests are ignored by Git because they can
contain candidate-identifying information.

## 7. Inspect Embeddings In PostgreSQL

Open the PostgreSQL shell:

```powershell
docker compose exec postgres psql -U talent_ranker -d talent_ranker
```

Run these queries:

```sql
SELECT candidate_id, ordinal, parent_ordinal, section,
       vector_dims(embedding) AS dimensions,
       left(content, 100) AS child_preview
FROM resume_chunks
ORDER BY candidate_id, ordinal;

SELECT candidate_id, ordinal,
       subvector(embedding, 1, 8) AS first_eight_dimensions
FROM resume_chunks
LIMIT 10;

SELECT candidate_id, count(*) AS chunk_count
FROM resume_chunks
GROUP BY candidate_id
ORDER BY candidate_id;
```

Enter `\q` to leave `psql`.

For a graphical view in VS Code, install the Microsoft PostgreSQL extension and create a
connection with:

```text
Host: localhost
Port: 5432
Database: talent_ranker
User: talent_ranker
Password: talent-ranker-local
SSL: disabled for local development
```

Open a query editor for that connection and run the same SQL. Displaying a few dimensions with
`subvector` is more useful than rendering all 384 values.

## 8. Start The FastAPI Backend

Use a new PowerShell terminal from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn talent_ranker.api:app --reload --host 127.0.0.1 --port 8000
```

Open:

- Health check: `http://127.0.0.1:8000/health`
- Interactive API documentation: `http://127.0.0.1:8000/docs`

Create a calibration draft after creating `job.txt`:

```powershell
$request = @{
  job_id = "senior-ai-engineer"
  job_description = Get-Content .\job.txt -Raw
} | ConvertTo-Json

$profile = Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/jobs/calibrate `
  -Method Post `
  -ContentType "application/json" `
  -Body $request
```

Review or edit `$profile.priorities`, then approve the version and rank candidates:

```powershell
$approval = @{ approved_by = "recruiter@example.com" } | ConvertTo-Json
$profile = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/job-profiles/$($profile.profile_version_id)/approve" `
  -Method Post `
  -ContentType "application/json" `
  -Body $approval

$rankRequest = @{
  job_id = $profile.job_id
  job_profile_version_id = $profile.profile_version_id
  top_k = 10
} | ConvertTo-Json

$response = Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/rank `
  -Method Post `
  -ContentType "application/json" `
  -Body $rankRequest
```

The first ranking request may take longer while the reranker loads into memory.

Use the returned `run_id` and a candidate ID to retrieve the evidence saved for that exact result:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/ranking-runs/$($response.run_id)/candidates/CAND_0001/evidence" `
  -Method Get
```

## 9. Start The Frontend

Use another PowerShell terminal:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The frontend calls FastAPI on `http://localhost:8000` by default.

## 10. Stop Local Services

Stop the API and frontend with `Ctrl+C` in their terminals. Stop PostgreSQL with:

```powershell
docker compose down
```

This keeps the PostgreSQL volume and indexed data.
