import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSavedRun } from "./api";
import type { SavedRunPage } from "./api";
import { batchApi } from "./batchApi";
import type { ContactPreview } from "./batchApi";
import { BatchPreparation } from "./BatchPreparation";
import { ResumeSourceCard } from "./ResumeSourceCard";
import { ExternalEvidenceCard } from "./ExternalEvidenceCard";
import { criterionLabel, rankingExplanation } from "./rankingExplanation";

type Props = { jobId: string; runId: string; token: string };

export function AgentCandidateCards({ jobId, runId, token }: Props) {
  const [run, setRun] = useState<SavedRunPage | null>(null);
  const [names, setNames] = useState<Record<string, ContactPreview>>({});
  const [namesLoaded, setNamesLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
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

  async function saveName(event: FormEvent, candidateId: string) {
    event.preventDefault();
    if (!nameDraft.trim()) return;
    try {
      const saved = await batchApi.setName(candidateId, nameDraft.trim(), token);
      setNames((current) => ({ ...current, [candidateId]: {
        ...current[candidateId], candidate_id: candidateId, display_name: saved.display_name,
        name_source: "recruiter_verified", email: current[candidateId]?.email ?? null,
        contactable: current[candidateId]?.contactable ?? false,
      } }));
      setEditing(null); setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save candidate name.");
    }
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
        const explanation = rankingExplanation(candidate);
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
          {identity && <button type="button" className="agent-candidate-edit" onClick={() => {
            setEditing(candidate.candidate_id); setNameDraft(identity.display_name ?? "");
          }}>{identity.display_name ? "Correct name" : "Add name"}</button>}
          {editing === candidate.candidate_id && <form onSubmit={(event) => saveName(event, candidate.candidate_id)}>
            <input aria-label={`Verified name for ${candidate.candidate_id}`} value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)} maxLength={80} required />
            <button type="submit">Save</button>
          </form>}
          <ul className="agent-candidate-explanation">
            <li><strong>Skills:</strong> {explanation.skills}</li>
            <li><strong>Experience:</strong> {explanation.experience}</li>
            <li><strong>Why ranked:</strong> {explanation.why}</li>
          </ul>
          <details><summary>Review criterion evidence</summary>
            {(candidate.requirement_evidence?.length ?? 0) > 0
              ? <ul>{candidate.requirement_evidence?.map((item, index) =>
                <li key={index}><strong>{criterionLabel(item)}</strong> — {item.status.replaceAll("_", " ")}
                  {item.passage && <p>{item.passage}</p>}</li>)}</ul>
              : <p>No structured criterion evidence was saved for this run.</p>}
          </details>
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
