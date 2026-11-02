import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getSavedRun } from "./api";
import type { CandidateScore, SavedRunPage } from "./api";
import { BatchPreparation } from "./BatchPreparation";
import { batchApi } from "./batchApi";
import type { ContactPreview } from "./batchApi";
import { useRecruiterSession } from "./RecruiterLayout";
import { ResumeSourceCard } from "./ResumeSourceCard";
import { ExternalEvidenceCard } from "./ExternalEvidenceCard";

export function ShortlistPage() {
  const { jobId, runId } = useParams();
  const navigate = useNavigate();
  const recruiterSession = useRecruiterSession();
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
  const [token, setToken] = useState(recruiterSession.token);
  const [activeToken, setActiveToken] = useState(recruiterSession.token);
  const [identities, setIdentities] = useState<Record<string, ContactPreview>>({});
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [identityLoaded, setIdentityLoaded] = useState(false);
  const [identityRequest, setIdentityRequest] = useState(0);
  const [editingNameId, setEditingNameId] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);

  useEffect(() => {
    if (!recruiterSession.token) return;
    setToken(recruiterSession.token);
    setActiveToken(recruiterSession.token);
  }, [recruiterSession.token]);

  const loadedIds = candidates.map((candidate) => candidate.candidate_id).join("|");
  useEffect(() => {
    if (!activeToken || !loadedIds) return;
    let current = true;
    batchApi.contacts(loadedIds.split("|"), activeToken)
      .then((items) => {
        if (!current) return;
        setIdentities(Object.fromEntries(items.map((item) => [item.candidate_id, item])));
        setIdentityLoaded(true);
        setIdentityError(null);
        recruiterSession.setToken(activeToken);
      })
      .catch((cause: unknown) => {
        if (current) setIdentityError(cause instanceof Error ? cause.message : "Could not load candidate names.");
      });
    return () => { current = false; };
  }, [activeToken, loadedIds, identityRequest, recruiterSession.setToken]);

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

  async function saveName(event: FormEvent, candidateId: string) {
    event.preventDefault();
    if (!activeToken || !nameDraft.trim()) return;
    setSavingName(true);
    try {
      const saved = await batchApi.setName(candidateId, nameDraft.trim(), activeToken);
      setIdentities((previous) => ({ ...previous, [candidateId]: {
        ...previous[candidateId], candidate_id: candidateId, display_name: saved.display_name,
        name_source: "recruiter_verified",
        email: previous[candidateId]?.email ?? null,
        contactable: previous[candidateId]?.contactable ?? false,
      } }));
      setEditingNameId(null);
      setIdentityError(null);
    } catch (cause) {
      setIdentityError(cause instanceof Error ? cause.message : "Could not save candidate name.");
    } finally { setSavingName(false); }
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
      {!identityLoaded && <p className="hint" role="status">
        {identityError ? "Candidate names could not be loaded; check recruiter access and retry."
          : activeToken ? "Loading protected candidate names…"
            : "Enter recruiter access below to show candidate names on the cards."}
      </p>}
      <form className="identity-access" onSubmit={(event) => {
        event.preventDefault();
        setRun(null);
        setCandidates([]);
        setSelected(new Set());
        setIdentities({});
        setIdentityLoaded(false);
        setIdentityError(null);
        recruiterSession.setToken(token.trim());
        setActiveToken(token.trim());
        setRequestCursor(0);
        setRetry((value) => value + 1);
        setIdentityRequest((value) => value + 1);
      }}>
        <button type="submit">{identityLoaded ? "Refresh candidate names" : "Show candidate names"}</button>
        <span className="hint">Candidate IDs remain for matching and audit.</span>
      </form>
      {identityError && <p className="error" role="alert">{identityError}</p>}
      {run && candidates.length > 0 && (
        <div className="selection-toolbar">
          <button type="button" className="secondary-button" onClick={toggleLoaded}>
            {candidates.every((candidate) => selected.has(candidate.candidate_id))
              ? "Deselect loaded candidates" : "Select loaded candidates"}
          </button>
          <strong aria-live="polite">{selected.size} selected</strong>
          <button type="button" disabled={!selected.size || !run.job_profile_version_id}
            onClick={() => setPreparing(true)}>Prepare selected candidates</button>
          <button type="button" className="secondary-button" disabled={!run.job_profile_version_id}
            onClick={() => setPreparing(true)}>Agent bulk selection</button>
          <span className="hint">Choose candidates yourself or preview a rule for this saved run.</span>
        </div>
      )}
      <section className="shortlist-grid" aria-label="Ranked candidates">
        {candidates.map((candidate) => (
          <article key={candidate.candidate_id} className={`result-card ${selected.has(candidate.candidate_id) ? "selected" : ""}`}>
            <label className="candidate-select">
              <input type="checkbox" checked={selected.has(candidate.candidate_id)} onChange={() => toggle(candidate.candidate_id)} />
              <span>Select {identities[candidate.candidate_id]?.display_name || candidate.candidate_id}</span>
            </label>
            <div>
              <span>Rank #{candidate.rank}</span>
              <h2>{identities[candidate.candidate_id]?.display_name || (identityLoaded ? "Name needs review" : "Name hidden")}</h2>
              <small className="candidate-record-id">Record ID: {candidate.candidate_id}</small>
              {identities[candidate.candidate_id]?.name_source === "legacy_resume_header" &&
                <small className="candidate-record-id">Extracted from resume · verify before outreach</small>}
              {identityLoaded && <button type="button" className="name-review-button" onClick={() => {
                setEditingNameId(candidate.candidate_id);
                setNameDraft(identities[candidate.candidate_id]?.display_name ?? "");
              }}>{identities[candidate.candidate_id]?.display_name ? "Correct name" : "Add verified name"}</button>}
            </div>
            <strong title="Relative ranking index, not a probability of job fit">Ranking index {Math.round(candidate.score * 100)}/100</strong>
            {editingNameId === candidate.candidate_id && <form className="name-review-form"
              onSubmit={(event) => saveName(event, candidate.candidate_id)}>
              <label>Verified name from the resume
                <input value={nameDraft} maxLength={80} onChange={(event) => setNameDraft(event.target.value)} required />
              </label>
              <button type="submit" disabled={savingName || nameDraft.trim().length < 2}>Save name</button>
              <button type="button" className="secondary-button" onClick={() => setEditingNameId(null)}>Cancel</button>
            </form>}
            <p>{candidate.reasoning}</p>
            <ResumeSourceCard candidateId={candidate.candidate_id} token={activeToken} />
            <ExternalEvidenceCard candidateId={candidate.candidate_id} token={activeToken} />
          </article>
        ))}
      </section>
      {preparing && run?.job_profile_version_id && jobId && runId &&
        <BatchPreparation jobId={jobId} runId={runId} profileId={run.job_profile_version_id}
          selectedIds={[...selected]} onSelectRecipients={(ids) => setSelected(new Set(ids))}
          initialToken={activeToken} />}
      {loading && <p role="status">Loading shortlist…</p>}
      {!loading && run && candidates.length === 0 && <p>No candidates in this saved run.</p>}
      {!loading && nextCursor !== null && !error && (
        <button type="button" onClick={() => setRequestCursor(nextCursor)}>Load more candidates</button>
      )}
      {!loading && error && <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>}
    </main>
  );
}
