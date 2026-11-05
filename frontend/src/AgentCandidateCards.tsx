import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSavedRun } from "./api";
import type { SavedRunPage } from "./api";
import { batchApi } from "./batchApi";
import type { ContactPreview } from "./batchApi";
import { BatchPreparation } from "./BatchPreparation";
import { ResumeSourceCard } from "./ResumeSourceCard";
import { ExternalEvidenceCard } from "./ExternalEvidenceCard";
import { rankingBullets } from "./rankingExplanation";

type Props = { jobId: string; runId: string; token: string };

export function AgentCandidateCards({ jobId, runId, token }: Props) {
  const [run, setRun] = useState<SavedRunPage | null>(null);
  const [names, setNames] = useState<Record<string, ContactPreview>>({});
  const [namesLoaded, setNamesLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setRun(null); setNames({}); setNamesLoaded(false); setSelected(new Set()); setPreparing(false);
    setLoading(true); setError(null);
    getSavedRun(runId, 0, controller.signal).then((page) => {
      if (page.job_id !== jobId) throw new Error("This shortlist belongs to another job.");
      if (!controller.signal.aborted) setRun(page);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load candidates.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [jobId, runId, token]);

  const candidateIds = run?.items.map((candidate) => candidate.candidate_id).join("|") ?? "";
  useEffect(() => {
    if (!candidateIds || !token) return;
    let active = true;
    batchApi.contacts(candidateIds.split("|"), token).then((contacts) => {
      if (active) {
        setNames(Object.fromEntries(contacts.map((contact) => [contact.candidate_id, contact])));
        setNamesLoaded(true);
      }
    }).catch((cause: unknown) => {
      if (active) {
        setNamesLoaded(true);
        setError(cause instanceof Error ? cause.message : "Could not load candidate names.");
      }
    });
    return () => { active = false; };
  }, [candidateIds, token]);

  function toggle(candidateId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) => {
      if (!run) return current;
      return run.items.every((item) => current.has(item.candidate_id))
        ? new Set<string>() : new Set(run.items.map((item) => item.candidate_id));
    });
  }

  return <section className="agent-candidates" aria-label="Saved ranked candidates">
    <header className="agent-candidates-header">
      <div><small>SAVED SHORTLIST</small><h2>Top candidates</h2>
        <p>Ranking indexes are relative scores. Review the resume before acting on them.</p></div>
      <Link to={`/jobs/${encodeURIComponent(jobId)}/ranking-runs/${encodeURIComponent(runId)}`}>
        Open full shortlist
      </Link>
    </header>
    {loading && <p role="status">Loading candidate cards…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {run && <>
      <div className="agent-candidates-toolbar">
        <span>{run.items.length} of {run.total_count} ranked</span>
        <button type="button" className="secondary-button" onClick={toggleAll}>
          {run.items.every((item) => selected.has(item.candidate_id)) ? "Deselect all" : "Select all"}
        </button>
        <strong>{selected.size} selected</strong>
        <button type="button" disabled={!selected.size || !run.job_profile_version_id}
          onClick={() => setPreparing(true)}>Prepare selected</button>
      </div>
      <div className="agent-candidates-grid">{run.items.map((candidate) => {
        const identity = names[candidate.candidate_id];
        const bullets = rankingBullets(candidate);
        return <article key={candidate.candidate_id}
          className={`agent-candidate-card ${selected.has(candidate.candidate_id) ? "selected" : ""}`}>
          <label className="agent-candidate-select"><input type="checkbox"
            checked={selected.has(candidate.candidate_id)} onChange={() => toggle(candidate.candidate_id)} />
            Select {identity?.display_name || candidate.candidate_id}</label>
          <div className="agent-candidate-rank"><span>Rank #{candidate.rank}</span>
            <strong title="Relative ranking index, not a fit probability">
              {Math.round(candidate.score * 100)}/100</strong></div>
          <h3>{identity?.display_name || (namesLoaded ? "Name needs review" : "Loading name…")}</h3>
          <small>Record ID: {candidate.candidate_id}</small>
          {identity?.name_source === "legacy_resume_header" && <small>Extracted from resume · verify before outreach</small>}
          {bullets.length > 0 && <ul className="agent-candidate-explanation">
            {bullets.map((bullet, index) => <li key={index}>{bullet}</li>)}
          </ul>}
          <div className="agent-candidate-links">
            <ResumeSourceCard candidateId={candidate.candidate_id} token={token} />
            <ExternalEvidenceCard candidateId={candidate.candidate_id} token={token} />
          </div>
        </article>;
      })}</div>
      {preparing && run.job_profile_version_id && <BatchPreparation
        jobId={jobId} runId={runId} profileId={run.job_profile_version_id}
        selectedIds={[...selected]} onSelectRecipients={(ids) => setSelected(new Set(ids))}
        initialToken={token} />}
    </>}
  </section>;
}
