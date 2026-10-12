import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { batchApi } from "./batchApi";
import type { ContactPreview, JobConfig, QuestionDraft, SelectionPreview, SelectionRule } from "./batchApi";
import type { Campaign } from "./screeningApi";
import { invitationMessage, roleTitleFromJobId } from "./invitationMessage";
import { useRecruiterSession } from "./RecruiterLayout";

type Props = {
  jobId: string; runId: string; profileId: string; selectedIds: string[];
  onSelectRecipients: (ids: string[]) => void;
  initialToken?: string;
};

export function BatchPreparation({ jobId, runId, profileId, selectedIds, onSelectRecipients, initialToken = "" }: Props) {
  const navigate = useNavigate();
  const recruiterSession = useRecruiterSession();
  const [token, setToken] = useState(initialToken || recruiterSession.token);
  const [activeToken, setActiveToken] = useState("");
  const [questionDraft, setQuestionDraft] = useState<QuestionDraft | null>(null);
  const [latest, setLatest] = useState<JobConfig | null>(null);
  const [config, setConfig] = useState<JobConfig | null>(null);
  const [contacts, setContacts] = useState<ContactPreview[]>([]);
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [rule, setRule] = useState<SelectionRule>({ kind: "top_n", value: Math.max(1, selectedIds.length) });
  const [preview, setPreview] = useState<SelectionPreview | null>(null);
  const [roleTitle, setRoleTitle] = useState(() => roleTitleFromJobId(jobId));
  const [message, setMessage] = useState(() => invitationMessage(roleTitleFromJobId(jobId)));
  const [expiry, setExpiry] = useState(48);
  const [draft, setDraft] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedKey = selectedIds.join("|");

  useEffect(() => {
    if (!activeToken || !selectedKey) return;
    let active = true;
    batchApi.contacts(selectedKey.split("|"), activeToken).then((items) => {
      if (!active) return;
      setContacts(items);
      setEmails((previous) => Object.fromEntries(items.map((item) =>
        [item.candidate_id, previous[item.candidate_id] ?? item.email ?? ""])));
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not check contacts.");
    });
    return () => { active = false; };
  }, [activeToken, selectedKey]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const [draftQuestions, latestConfig] = await Promise.all([
        batchApi.questionDraft(jobId, profileId, token.trim()),
        batchApi.latestConfig(jobId, token.trim()),
      ]);
      setQuestionDraft(draftQuestions);
      setLatest(latestConfig);
      setConfig(latestConfig?.job_profile_version_id === profileId ? latestConfig : null);
      setActiveToken(token.trim());
      recruiterSession.setToken(token.trim());
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not prepare batch."); }
    finally { setBusy(false); }
  }

  async function createQuestions() {
    if (!questionDraft) return;
    setBusy(true);
    try {
      const created = await batchApi.createConfig(jobId, profileId, (latest?.version ?? 0) + 1,
        questionDraft, activeToken);
      setLatest(created);
      setConfig(created);
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save questions."); }
    finally { setBusy(false); }
  }

  async function saveContact(candidateId: string) {
    setBusy(true);
    try {
      await batchApi.setContact(candidateId, emails[candidateId]?.trim() ?? "", activeToken);
      setContacts(await batchApi.contacts(selectedIds, activeToken));
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save contact."); }
    finally { setBusy(false); }
  }

  async function previewRule() {
    setBusy(true);
    try {
      setPreview(await batchApi.preview(jobId, runId, rule, activeToken));
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not preview selection."); }
    finally { setBusy(false); }
  }

  async function saveProposal() {
    if (!config || !preview || !selectedIds.length) return;
    setBusy(true);
    try {
      const proposed = draft ?? await batchApi.propose(jobId, runId, config.id, rule, message, expiry, activeToken);
      setDraft(proposed);
      const edited = await batchApi.edit(proposed.id, proposed.revision, selectedIds, message, activeToken);
      setDraft(edited);
      navigate(`/screening/campaigns/${edited.id}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save campaign."); }
    finally { setBusy(false); }
  }

  const byId = new Map(contacts.map((item) => [item.candidate_id, item]));
  const contactsReady = selectedIds.length > 0 && selectedIds.every((id) => byId.get(id)?.contactable && byId.get(id)?.email);
  const changedEmails = selectedIds.some((id) => (emails[id] ?? "").trim() !== (byId.get(id)?.email ?? ""));
  const validMessage = message.split("{screening_link}").length === 2;
  function changeRoleTitle(value: string) {
    if (message === invitationMessage(roleTitle)) setMessage(invitationMessage(value));
    setRoleTitle(value);
  }
  return <section className="screening-panel batch-preparation" aria-label="Prepare screening batch">
    <h2>Prepare screening batch</h2>
    <p className="hint">The {selectedIds.length} candidates below will be the final recipients. Nothing sends until you approve the saved campaign.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!activeToken ? <form onSubmit={connect}>
      <label>Recruiter bearer token <input type="password" autoComplete="off" value={token}
        onChange={(event) => setToken(event.target.value)} required /></label>
      <button disabled={busy}>Load screening setup</button>
    </form> : <>
      <div className="batch-section">
        <h3>1. Questions for this job</h3>
        {config ? <p>Using approved question set v{config.version}: {config.questions.must_haves.map((item) => item.text).join(", ")}</p>
          : <><p>Confirm these approved must-haves with each candidate:</p>
            <ul>{questionDraft?.must_haves.map((item) => <li key={item.id}>{item.text}</li>)}</ul>
            <button type="button" disabled={busy} onClick={createQuestions}>Save screening questions</button></>}
      </div>
      <div className="batch-section">
        <h3>2. Agent bulk selection or manual selection</h3>
        <p className="hint">The rule uses scores from this saved run. Preview it, then choose whether to use its proposed recipients or keep your manual selection.</p>
        <div className="batch-controls">
          <label>Rule <select value={rule.kind} onChange={(event) => {
            const kind = event.target.value as SelectionRule["kind"];
            setRule({ kind, value: kind === "score_threshold" ? 0.5 : Math.max(1, Math.round(rule.value)) });
            setPreview(null);
          }}><option value="top_n">Top N</option><option value="rank_cutoff">Rank cutoff</option>
            <option value="score_threshold">Score threshold</option></select></label>
          <label>Value <input type="number" min={rule.kind === "score_threshold" ? 0 : 1}
            max={rule.kind === "score_threshold" ? 1 : 10000} step={rule.kind === "score_threshold" ? 0.01 : 1}
            value={rule.value} onChange={(event) => { setRule({ ...rule, value: Number(event.target.value) }); setPreview(null); }} /></label>
          <button type="button" disabled={busy || !Number.isFinite(rule.value) ||
            (rule.kind === "score_threshold" ? rule.value < 0 || rule.value > 1 : rule.value < 1 || !Number.isInteger(rule.value))}
            onClick={previewRule}>Preview</button>
        </div>
        {preview && <>
          <p>Rule proposes {preview.matching_count} candidates; {preview.candidates.filter((item) => !item.has_contact).length} need contact details.</p>
          <button type="button" className="secondary-button" disabled={busy || !preview.candidates.length}
            onClick={() => onSelectRecipients(preview.candidates.map((item) => item.candidate_id))}>
            Use proposed selection
          </button>
          <p className="hint">Previewing does not change the recipient list. You can remove candidates below before saving.</p>
        </>}
      </div>
      <div className="batch-section">
        <h3>3. Check exact recipients</h3>
        {selectedIds.map((id) => <div className="batch-contact" key={id}>
          <strong>{byId.get(id)?.display_name || "Name needs review"}</strong>
          <span>{id}</span>
          <input aria-label={`Email for ${id}`} type="email" value={emails[id] ?? ""}
            onChange={(event) => setEmails({ ...emails, [id]: event.target.value })} placeholder="Candidate email" />
          <button type="button" className="secondary-button" disabled={busy || !emails[id]}
            onClick={() => saveContact(id)}>Save contact</button>
          <span>{byId.get(id)?.contactable ? "Contactable" : "Contact needed"}</span>
          <button type="button" className="secondary-button" disabled={busy}
            onClick={() => onSelectRecipients(selectedIds.filter((candidateId) => candidateId !== id))}>
            Remove
          </button>
        </div>)}
        {!selectedIds.length && <p className="hint">Select cards manually or use the proposed selection above.</p>}
      </div>
      <div className="batch-section">
        <h3>4. Save for recruiter approval</h3>
        <label>Role title <input value={roleTitle} onChange={(event) => changeRoleTitle(event.target.value)} />
          <span className="hint">Suggested from the job ID. Confirm the wording before sending.</span>
        </label>
        <label>Invitation message <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={8} /></label>
        <button type="button" className="secondary-button" onClick={() => setMessage(invitationMessage(roleTitle))}>Use suggested message</button>
        <label>Link expiry (hours) <input type="number" min={1} max={720} value={expiry}
          onChange={(event) => setExpiry(Number(event.target.value))} /></label>
        <button type="button" disabled={busy || !config || !preview || !contactsReady || changedEmails || !roleTitle.trim() || !validMessage}
          onClick={saveProposal}>Save proposed campaign</button>
        {!contactsReady && <p className="hint">Save a contactable email for every checked candidate before continuing.</p>}
        {changedEmails && <p className="hint">Save edited addresses before continuing.</p>}
        {draft && <p>Proposal saved as <Link to={`/screening/campaigns/${draft.id}`}>{draft.id}</Link>. Retry saving the final list if needed.</p>}
      </div>
    </>}
  </section>;
}
