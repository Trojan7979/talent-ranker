# Candidate Screening

This standalone FastAPI service takes one persisted `talent-ranker` ranking run, lets a recruiter
approve a batch, sends each selected candidate one expiring screening link, collects structured
answers, and produces deterministic outcomes. It neither ingests resumes nor ranks candidates.
Micro-viva is a future separate pipeline. The external orchestrator will pause for recruiter
approval before calling it; see [`../fitcheck.md`](../fitcheck.md).

## Install and run

Python 3.11+, PostgreSQL, and the upstream ranking schema are required. The package does not
import ranking models or an LLM client.

```powershell
cd candidate-screening
uv venv --python 3.11
uv pip install -e ".[dev]"
$env:SCREENING_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/talent_ranker"
$env:SCREENING_RECRUITER_TOKENS = '{"local-dev-token":"local-recruiter"}'
psql $env:SCREENING_DATABASE_URL -f db/schema.sql
uvicorn candidate_screening.api:app --port 8001
```

The ranking database must already contain `candidates`, `jobs`, `job_profile_versions`,
`ranking_runs`, and `ranking_results`. Run the screening migration after the upstream schema.
`db/schema.sql` owns only screening tables. The service uses a bounded psycopg connection pool.

The local bearer-token map is a development identity adapter. A production deployment must replace
it with the organization's authenticated recruiter principal. Candidate routes use the unique link
token. Keep API access logs from recording token-bearing URLs.

Copy `.env.example` for available settings. The default invite lifetime is 48 hours from approval.
Set `SCREENING_PUBLIC_BASE_URL` to the candidate form URL when the frontend is added; for API-only
testing it points to the invite API. No frontend is included here.

## Mock data and checks

The Postgres tests create a uniquely named test schema, minimal upstream candidates/job/ranking
fixtures, and the screening migration inside a transaction that is rolled back. They do not alter
the real ranking tables. The fake sender captures initial messages in tests.

```powershell
$env:SCREENING_TEST_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/talent_ranker"
pytest -q
ruff check .
ruff format --check .
```

Without `SCREENING_TEST_DATABASE_URL`, integration tests report as skipped. Use a disposable
database credential capable of creating schemas for the full check. Test files and Python modules
are kept around 250 lines or less.

## API flow

All recruiter requests use `Authorization: Bearer <configured-token>`. An approved job profile and
saved ranking run are prerequisites. The workflow is:

1. `PUT /screening/candidates/{candidate_id}/contact` sets a candidate's contact email, source,
   and contactability. The candidate must already exist; resume text is never used to find email.
2. `POST /screening/jobs/{job_id}/configs` freezes the five question groups and approved must-have
   confirmations for one profile version. The configured must-haves must match the approved profile.
3. `POST /screening/selections` previews `score_threshold`, `top_n`, or `rank_cutoff` for one job and
   pinned ranking run. It creates no campaign or invite. A preview without `ranking_run_id` resolves
   the latest run and returns its ID; use that ID in the next call.
4. `POST /screening/campaigns` creates a proposal with the pinned run, config ID, selection rule,
   `message_template` containing exactly one `{screening_link}`, and optional `expiry_hours`.
   `PATCH /screening/campaigns/{id}` may edit the final IDs and template while proposed; edits use
   `expected_revision`. `POST /screening/campaigns/{id}/reject` closes an unapproved proposal.
5. `POST /screening/campaigns/{id}/approve` requires recruiter auth and `expected_revision`.
   Approval checks every final candidate and contact, freezes the list, creates unique invites, and
   queues one initial email per candidate in one transaction. It does **not** claim email delivery.
6. `candidate-screening dispatch --once` sends a bounded batch from the delivery outbox. A scheduler
   may run this command repeatedly. `SCREENING_SENDER_BACKEND=fake` makes local tests safe;
   `smtp` uses the configured host, sender address, port, and optional credentials over STARTTLS.
   Provider acceptance changes an invite to `sent`; SMTP acceptance does not prove inbox delivery.
7. Candidate API: `GET /screening/invites/{token}` reads questions; `POST .../opened` records an
   explicit open event; `POST .../started` begins screening; `PUT .../responses` saves a draft;
   `POST .../complete` submits answers and creates a summary; `POST .../decline` declines. Draft
   and completion bodies use `{"expected_revision":0,"answers":{...}}`.
8. `candidate-screening expire --once` expires due invites in bounded batches. Active token
   requests also enforce expiry immediately, so correctness does not depend on sweep timing.
9. `GET /screening/campaigns/{id}/results` returns completed cases with outcome counts, review
   cases first, cursor pagination, optional outcome filter, and an alternate `completed_at` sort.
   `GET /screening/summaries/{id}` returns one completed summary.

Example preview body:

```json
{
  "job_id": "senior-ai-engineer",
  "ranking_run_id": "22222222-2222-2222-2222-222222222222",
  "rule": {"kind": "top_n", "value": 20}
}
```

Example answer body (requirement IDs come from the candidate-facing question response):

```json
{
  "expected_revision": 0,
  "answers": {
    "qualifications": [{"requirement_id": "python", "confirmation": "yes"}],
    "interest": "interested",
    "availability": {"status": "answered", "earliest_start_date": "2026-10-15"},
    "notice_period": {"status": "answered", "days": 21},
    "salary": {
      "status": "answered", "minimum": "110000", "maximum": "140000",
      "currency": "USD", "period": "year", "negotiable": false
    }
  }
}
```

The three outcomes are exactly `proceed_to_interview`, `needs_recruiter_review`, and
`do_not_proceed`. Answers are self-reported. Uncertain, missing, inconsistent, or non-comparable
answers need recruiter review by default; a confirmed violation rejects automatically only when
an approved job rule explicitly marks it as a hard fail. A completed `not_interested` response is
`do_not_proceed`; an explicit decline remains a terminal invite without a completed summary.

The worker retries the same link after transient failures with bounded exponential backoff. An
outbox prevents lost work after approval, but a provider timeout after accepting an email can
still produce a duplicate message. Unsent/expired/deleted/uncontactable candidates are skipped.
`409` means a stale revision or invalid transition, `410` means an expired link, and `422` means
invalid request input. Tokens are never returned in recruiter result lists.

## External orchestrator contract

The later orchestrator can expose tools equivalent to `propose_screening_batch`,
`create_screening_campaign`, `get_screening_campaign`, and `get_screening_results`. The approval
tool must use an authenticated recruiter decision, not an agent-provided `approved_by` string.
After completion the orchestrator can poll results, pause for a separate recruiter progression
decision, then invoke the separate micro-viva pipeline if job policy requires it. A screening pass
alone does not authorize viva. See the versioned handoff proposal in `fitcheck.md` for candidate,
summary, approved criteria, frozen resume evidence, and progression-decision references.
