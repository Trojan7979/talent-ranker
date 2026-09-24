# Candidate Screening

Standalone FastAPI service for the screening stage following a persisted `talent-ranker` run. See
[`../fitcheck.md`](../fitcheck.md) for the stepwise implementation plan and future orchestrator/viva
handoff. This directory is being implemented in verified slices; only the health endpoint is
available in the initial skeleton.

```powershell
cd candidate-screening
uv pip install -e ".[dev]"
uvicorn candidate_screening.api:app --port 8001
pytest
```

No ranking models or LLM client are imported by this package. A later orchestrator will call the
screening API to propose batches and read outcomes. Only an authenticated recruiter can approve a
batch for delivery; screening completion alone does not authorize a future viva session.
