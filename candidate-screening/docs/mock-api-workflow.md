# Ranking → screening: mock API validation

Run this from the repository root in PowerShell. The first pass uses a **separate
`screening_mock` database**, a saved ranking fixture, `.invalid` recipient addresses,
and the fake sender. It never calls a ranking model or sends email. Run the Gmail
pilot separately after these checks; the API-only inbox test need not wait for UI.

## 1. Automated contract gate

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_job_calibration_api.py
$env:SCREENING_TEST_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/talent_ranker"
Push-Location candidate-screening
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

The first suite checks ranking's calibration/approval API boundaries. The second
uses rolled-back Postgres fixtures to check selection from a pinned ranking run,
campaign approval, four unique fake links, lifecycle rules, deterministic outcomes,
and recruiter results. A failure here blocks the manual pass.

## 2. Prepare a disposable database

Start Docker Desktop, then run the following once. If `screening_mock` already exists,
skip `createdb`; the fixture is safe to reapply in that dedicated database.

```powershell
docker compose up -d
docker compose exec -T postgres createdb -U talent_ranker screening_mock
Get-Content db\schema.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U talent_ranker -d screening_mock
Get-Content candidate-screening\db\schema.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U talent_ranker -d screening_mock
Get-Content candidate-screening\examples\mock-ranking.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U talent_ranker -d screening_mock
```

The fixture creates job `screening-mock-job`, approved profile
`55555555-5555-5555-5555-555555555555`, ranking run
`66666666-6666-6666-6666-666666666666`, and candidates `CAND_8991`–`CAND_8994`
with scores 0.90, 0.80, 0.70, and 0.60. It simulates the **persisted ranking output**;
it does not claim to validate the retrieval/reranking model.

## 3. Start both APIs against that database

In terminal A, from the repository root:

```powershell
$env:TALENT_RANKER_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/screening_mock"
.\.venv\Scripts\python.exe -m uvicorn talent_ranker.api:app --host 127.0.0.1 --port 8000
```

In terminal B, from `candidate-screening`:

```powershell
$env:SCREENING_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/screening_mock"
$env:SCREENING_SENDER_BACKEND = "fake"
$env:SCREENING_RECRUITER_TOKENS = '{"mock-token":"mock-recruiter"}'
.\.venv\Scripts\python.exe -m uvicorn candidate_screening.api:app --host 127.0.0.1 --port 8001
```

Back in terminal C at the repository root, set request variables and check both
health endpoints. The ranking evidence response proves the upstream API can read
the same pinned run that screening will consume:

```powershell
$ranker = "http://127.0.0.1:8000"
$screening = "http://127.0.0.1:8001"
$headers = @{ Authorization = "Bearer mock-token" }
$runId = "66666666-6666-6666-6666-666666666666"
$profileId = "55555555-5555-5555-5555-555555555555"
Invoke-RestMethod "$ranker/health"
Invoke-RestMethod "$screening/health"
Invoke-RestMethod "$ranker/ranking-runs/$runId/candidates/CAND_8991/evidence"
```

Expected: both health checks return `ok`; evidence reports `CAND_8991`, rank 1,
score 0.90, and the pinned run/profile IDs.

## 4. Preview, configure, and propose without sending

```powershell
$preview = Invoke-RestMethod "$screening/screening/selections" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{
  job_id = 'screening-mock-job'; ranking_run_id = $runId
  rule = @{ kind = 'top_n'; value = 4 }
} | ConvertTo-Json -Depth 6)
$preview.candidates | Select-Object candidate_id, rank, score, has_contact

$config = Invoke-RestMethod "$screening/screening/jobs/screening-mock-job/configs" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{
  job_profile_version_id = $profileId
  questions = @{ version = 1; must_haves = @(@{ id = 'python'; text = 'Python' }) }
} | ConvertTo-Json -Depth 6)

$campaign = Invoke-RestMethod "$screening/screening/campaigns" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{
  job_id = 'screening-mock-job'; ranking_run_id = $runId; config_id = $config.id
  rule = @{ kind = 'top_n'; value = 4 }
  message_template = 'Complete screening: {screening_link}'
} | ConvertTo-Json -Depth 6)
$campaign | Select-Object id, status, revision, proposed_candidate_ids
```

Expected: four ordered candidates; `has_contact=false` before contact setup;
campaign status `proposed`, revision 1. No invite or outbox entry exists yet.

## 5. Exercise the recruiter approval gate

First, try approving with no contacts. Expect HTTP `409` listing blockers; no
candidate should be silently dropped. Then set four fake contacts, edit the final
batch explicitly, and approve revision 2:

```powershell
try {
  Invoke-RestMethod "$screening/screening/campaigns/$($campaign.id)/approve" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"expected_revision":1}'
} catch { $_.Exception.Response.StatusCode }

foreach ($number in 8991..8994) {
  $candidateId = "CAND_$number"
  Invoke-RestMethod "$screening/screening/candidates/$candidateId/contact" -Method Put -Headers $headers -ContentType 'application/json' -Body (@{
    email = "mock-$number@example.invalid"; source = 'mock-api-walkthrough'
  } | ConvertTo-Json) | Out-Null
}

$campaign = Invoke-RestMethod "$screening/screening/campaigns/$($campaign.id)" -Method Patch -Headers $headers -ContentType 'application/json' -Body (@{
  expected_revision = 1
  final_candidate_ids = @('CAND_8991','CAND_8992','CAND_8993','CAND_8994')
  message_template = 'Your screening link: {screening_link}'
} | ConvertTo-Json -Depth 6)
$campaign = Invoke-RestMethod "$screening/screening/campaigns/$($campaign.id)/approve" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"expected_revision":2}'
$campaign | Select-Object status, approved_by, final_candidate_ids
```

Expected: `approved_by=mock-recruiter`, four final IDs, and four queued invites.
Approval records a decision; it does **not** send. Run the fake worker only for this
campaign. From terminal C:

```powershell
Push-Location candidate-screening
$env:SCREENING_DATABASE_URL = "postgresql://talent_ranker:talent-ranker-local@localhost:5432/screening_mock"
$env:SCREENING_SENDER_BACKEND = "fake"
.\.venv\Scripts\candidate-screening.exe dispatch --once --campaign-id $campaign.id --limit 4
Pop-Location
```

Expected worker counts: `sent=4`, `failed=0`, `cancelled=0`. Here `sent` means the
fake provider accepted the message. Retrieve these **mock-only** tokens from the
disposable database; real tokens must not appear in recruiter result responses:

```powershell
$rows = docker compose exec -T postgres psql -U talent_ranker -d screening_mock -t -A -F ',' -c "SELECT candidate_id,token FROM screening_invites WHERE campaign_id='$($campaign.id)' ORDER BY candidate_id"
$tokens = @{}
foreach ($row in $rows) { $parts = $row.Trim().Split(','); $tokens[$parts[0]] = $parts[1] }
```

## 6. Exercise candidate lifecycle and all outcomes

One candidate completes all five groups and proceeds; one omits required answers
and needs review; one declines interest and does not proceed; one declines the
invite (no completed summary). Candidate requests use their link tokens, not the
recruiter bearer token.

```powershell
$url1 = "$screening/screening/invites/$($tokens['CAND_8991'])"
Invoke-RestMethod $url1 | Select-Object status, questions
Invoke-RestMethod "$url1/opened" -Method Post | Out-Null
Invoke-RestMethod "$url1/started" -Method Post | Out-Null
$startDate = (Get-Date).ToUniversalTime().Date.AddDays(14).ToString('yyyy-MM-dd')
$proceed = Invoke-RestMethod "$url1/complete" -Method Post -ContentType 'application/json' -Body (@{
  expected_revision = 0
  answers = @{
    qualifications = @(@{ requirement_id = 'python'; confirmation = 'yes' })
    interest = 'interested'
    availability = @{ status = 'answered'; earliest_start_date = $startDate }
    notice_period = @{ status = 'answered'; days = 14 }
    salary = @{ status = 'answered'; minimum = '100000'; maximum = '120000'; currency = 'USD'; period = 'year' }
  }
} | ConvertTo-Json -Depth 8)

$url2 = "$screening/screening/invites/$($tokens['CAND_8992'])"
Invoke-RestMethod "$url2/started" -Method Post | Out-Null
$review = Invoke-RestMethod "$url2/complete" -Method Post -ContentType 'application/json' -Body '{"expected_revision":0,"answers":{"interest":"interested"}}'

$url3 = "$screening/screening/invites/$($tokens['CAND_8993'])"
Invoke-RestMethod "$url3/started" -Method Post | Out-Null
$stop = Invoke-RestMethod "$url3/complete" -Method Post -ContentType 'application/json' -Body '{"expected_revision":0,"answers":{"interest":"not_interested"}}'

$url4 = "$screening/screening/invites/$($tokens['CAND_8994'])"
$declined = Invoke-RestMethod "$url4/decline" -Method Post
$proceed.outcome; $review.outcome; $stop.outcome; $declined.status
```

Expected: `proceed_to_interview`, `needs_recruiter_review`,
`do_not_proceed`, and `declined`, respectively. Missing salary and other required
answers appear in `$review.missing`.

## 7. Verify recruiter review and failure cases

```powershell
$results = Invoke-RestMethod "$screening/screening/campaigns/$($campaign.id)/results" -Headers $headers
$results.counts
$results.items | Select-Object candidate_id, outcome
Invoke-RestMethod "$screening/screening/summaries/$($review.id)" -Headers $headers
```

Expected: one completed case in each outcome; review appears first; the declined
invite is absent from completed summaries; result items contain no link token.
Check that unauthenticated results return `401`, starting the declined invite returns
`409`, and a repeated fake dispatch sends zero. The automated suite additionally
checks stale revisions, duplicate completion, expired links (`410`), and sweep.

## 8. Frontend readiness gate and later live pilot

Start frontend work after the mock pass demonstrates a stable ranking-run handoff,
recruiter selection/edit/approval, four unique links, candidate form transitions,
three outcomes, and review-first results. The UI should consume these APIs; it
should not calculate outcomes or call the email provider itself.

The real four-inbox Gmail pilot is a **separate** pass: replace mock contacts with
the two Gmail, one Outlook.com, and one Microsoft 365 addresses; use a reachable
HTTPS `SCREENING_PUBLIC_BASE_URL`; authorize the fifth Gmail sender; review the
campaign; then explicitly switch the dispatch worker to `gmail_api`. Never switch
the sender backend for this mock walkthrough.
