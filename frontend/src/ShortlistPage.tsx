import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getSavedRun } from "./api";
import type { CandidateScore, SavedRunPage } from "./api";
import { BatchPreparation } from "./BatchPreparation";

export function ShortlistPage() {
  const { jobId, runId } = useParams();
  const navigate = useNavigate();
  const [campaignId, setCampaignId] = useState("");
  const [run, setRun] = useState<SavedRunPage | null>(null);
  const [candidates, setCandidates] = useState<CandidateScore[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [requestCursor, setRequestCursor] = useState<number | null>(0);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId || !jobId || requestCursor === null) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getSavedRun(runId, requestCursor, controller.signal)
      .then((page) => {
        if (page.job_id !== jobId) throw new Error("This shortlist belongs to another job.");
        setRun(page);
        setCandidates((previous) => requestCursor === 0 ? page.items : [...previous, ...page.items]);
        setNextCursor(page.next_after_rank);
        setRequestCursor(null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load shortlist.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [jobId, runId, requestCursor, retry]);

  function toggle(candidateId: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }

  function toggleLoaded() {
    setSelected((previous) => {
      const next = new Set(previous);
      const allSelected = candidates.every((candidate) => next.has(candidate.candidate_id));
      for (const candidate of candidates) {
        if (allSelected) next.delete(candidate.candidate_id);
        else next.add(candidate.candidate_id);
      }
      return next;
    });
  }

  return (
    <main className="shortlist-workspace">
      <header className="shortlist-header">
        <Link to="/ranking">← Ranking workspace</Link>
        <h1>Saved shortlist</h1>
        <p>Job {jobId} · Run {runId}</p>
        {run && <p>{run.total_count} candidates · Criteria version {run.job_profile_version_id ?? "unavailable"}</p>}
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <form className="open-campaign" onSubmit={(event) => {
        event.preventDefault();
        navigate(`/screening/campaigns/${encodeURIComponent(campaignId.trim())}`);
      }}>
        <label>Open an existing screening campaign
          <input value={campaignId} onChange={(event) => setCampaignId(event.target.value)}
            placeholder="Campaign ID" required />
        </label>
        <button type="submit" disabled={!campaignId.trim()}>Open campaign</button>
      </form>
      {run && candidates.length > 0 && (
        <div className="selection-toolbar">
          <button type="button" className="secondary-button" onClick={toggleLoaded}>
            {candidates.every((candidate) => selected.has(candidate.candidate_id))
              ? "Deselect loaded candidates" : "Select loaded candidates"}
          </button>
          <strong aria-live="polite">{selected.size} selected</strong>
          <button type="button" disabled={!selected.size || !run.job_profile_version_id}
            onClick={() => setPreparing(true)}>Prepare screening batch</button>
          <span className="hint">Select the candidates to contact, then prepare the batch.</span>
        </div>
      )}
      <section className="shortlist-grid" aria-label="Ranked candidates">
        {candidates.map((candidate) => (
          <article key={candidate.candidate_id} className={`result-card ${selected.has(candidate.candidate_id) ? "selected" : ""}`}>
            <label className="candidate-select">
              <input type="checkbox" checked={selected.has(candidate.candidate_id)} onChange={() => toggle(candidate.candidate_id)} />
              <span>Select {candidate.candidate_id}</span>
            </label>
            <div>
              <span>Rank #{candidate.rank}</span>
              <h2>{candidate.candidate_id}</h2>
            </div>
            <strong>Ranking score {Math.round(candidate.score * 100)}%</strong>
            <p>{candidate.reasoning}</p>
          </article>
        ))}
      </section>
      {preparing && run?.job_profile_version_id && jobId && runId &&
        <BatchPreparation jobId={jobId} runId={runId} profileId={run.job_profile_version_id}
          selectedIds={[...selected]} />}
      {loading && <p role="status">Loading shortlist…</p>}
      {!loading && run && candidates.length === 0 && <p>No candidates in this saved run.</p>}
      {!loading && nextCursor !== null && !error && (
        <button type="button" onClick={() => setRequestCursor(nextCursor)}>Load more candidates</button>
      )}
      {!loading && error && <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>}
    </main>
  );
}
