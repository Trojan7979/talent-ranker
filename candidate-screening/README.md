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
candidate-screening-api --reload
```

The ranking database must already contain `candidates`, `jobs`, `job_profile_versions`,
`ranking_runs`, and `ranking_results`. Run the screening migration after the upstream schema.
`db/schema.sql` owns only screening tables. The service uses a bounded psycopg connection pool.

The local bearer-token map is a development identity adapter. A production deployment must replace
it with the organization's authenticated recruiter principal. Candidate routes use the unique link
token. Keep API access logs from recording token-bearing URLs.

Copy `.env.example` for available settings. The default invite lifetime is 48 hours from approval.
`SCREENING_API_PORT` defaults to 8001; set it in `.env` to change the listening port when using
`candidate-screening-api`. From this directory, `uv run candidate-screening-api --reload` also works.
Set `SCREENING_PUBLIC_BASE_URL` to the frontend candidate route, such as
`http://127.0.0.1:5173/s` for a same-computer pilot, before approving a campaign.

## Four-inbox Gmail sender pilot

One fifth Gmail account sends the four screening links. Two Gmail and two Outlook/Microsoft 365
accounts are recipients; receiving an email does not require Microsoft Graph or an Outlook API.
The backend connects directly to the [Gmail API](https://developers.google.com/workspace/gmail/api/guides/sending)
with the send-only OAuth scope. MCP is not part of delivery.

1. Copy `.env.example` to `.env` in this directory. Set `SCREENING_SENDER_BACKEND=gmail_api` and
   paste the **fifth sender Gmail address** into `SCREENING_GMAIL_SENDER_EMAIL`. `.env` is ignored
   by Git. Keep `SCREENING_RECRUITER_TOKENS` set for the local recruiter API.
2. In Google Cloud, enable the Gmail API, configure the OAuth consent screen, and create a
   **Desktop app** OAuth client. For a personal Gmail test sender, configure an external audience
   and add that fifth account as a test user if the consent screen is in testing. Download the
   client JSON to `secrets/gmail-desktop-client.json` under this directory. The `secrets/` folder
   is ignored by Git. See the [official Python setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python).
3. Install the optional sender dependencies and authorize locally. Sign into the **fifth Gmail
   account** in the browser consent window. Only the
   [`gmail.send` scope](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send)
   is requested. The resulting refresh token is saved to `.tokens/gmail-sender.json`, also ignored
   by Git.

   ```powershell
   uv pip install -e ".[dev,gmail]"
   candidate-screening authorize-gmail
   ```

4. Copy `examples/pilot-contacts.example.json` to `secrets/pilot-contacts.json`. Replace its four
   example addresses with the **two recipient Gmail and two recipient Outlook addresses**, and
   replace the candidate IDs with four active candidates from the same persisted ranking run.
   Outlook/Microsoft 365 work or personal addresses can appear in this recipient list. The
   `provider` field labels the pilot mix; the sending worker does not route by recipient provider.
5. Start the API. Load the four addresses through its protected contact endpoint. The loader
   previews candidate IDs and provider labels by default; `--apply` writes the contacts and sends
   no email. Set the client bearer token to one of the keys in `SCREENING_RECRUITER_TOKENS`.

   ```powershell
   $env:SCREENING_RECRUITER_TOKEN = "local-dev-token"
   python scripts/load_pilot_contacts.py --file secrets/pilot-contacts.json
   python scripts/load_pilot_contacts.py --file secrets/pilot-contacts.json --apply
   ```

6. Preview one ranking run, propose a campaign, edit its final candidate IDs to those exact four,
   and approve it as the recruiter. Frontend approval now requests dispatch for that campaign.
   Before approval, set `SCREENING_PUBLIC_BASE_URL` to the
   reachable screening URL used in invite links. The default `localhost` URL only works on the
   machine running the API; a real inbox test across devices needs a reachable HTTPS host or
   development tunnel. If frontend dispatch cannot start or a queued invitation needs a later
   retry, run the Gmail worker for that campaign:

   ```powershell
   candidate-screening dispatch --once --campaign-id CAMPAIGN_UUID --limit 4
   ```

   Gmail dispatch requires `--campaign-id` so this pilot cannot pick up another campaign's queued
   mail. The command reports provider acceptance counts; check the four inboxes for receipt.
   The frontend opens each link at `/s/{token}` and displays the candidate question flow.

## Mock data and checks

For an ordered ranking-to-screening API walkthrough with a disposable database, fake
email delivery, candidate responses, and expected outcomes, use
[`docs/mock-api-workflow.md`](docs/mock-api-workflow.md).

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

The central frontend now supports the recruiter path without manual campaign API calls: open a
saved ranking shortlist, select candidate cards, choose **Prepare screening batch**, review or
create the job's approved-question configuration, preview the selection rule, and confirm each
recipient's email. Saving the proposal locks the checked cards as its editable final list. The
campaign page can edit that list and message until approval; approval requests initial delivery.
The backend remains the authority for eligibility, revision checks, and the final approval gate.

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
