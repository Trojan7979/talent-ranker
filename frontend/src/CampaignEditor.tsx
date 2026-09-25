import { useEffect, useState } from "react";
import { getSavedRun } from "./api";
import type { CandidateScore } from "./api";
import { batchApi } from "./batchApi";
import type { ContactPreview } from "./batchApi";
import type { Campaign } from "./screeningApi";

type Props = {
  campaign: Campaign;
  token: string;
  onSaved: (campaign: Campaign) => void;
  onCancel: () => void;
};

export function CampaignEditor({ campaign, token, onSaved, onCancel }: Props) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(campaign.final_candidate_ids ?? campaign.proposed_candidate_ids));
  const [message, setMessage] = useState(campaign.message_template);
  const [candidates, setCandidates] = useState<CandidateScore[]>([]);
  const [requestRank, setRequestRank] = useState<number | null>(0);
  const [nextRank, setNextRank] = useState<number | null>(null);
  const [contacts, setContacts] = useState<ContactPreview[]>([]);
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = [...selected];
  const idsKey = [...ids].sort().join("|");

  useEffect(() => {
    if (requestRank === null) return;
    let active = true;
    getSavedRun(campaign.ranking_run_id, requestRank).then((page) => {
      if (!active) return;
      setCandidates((previous) => requestRank === 0 ? page.items : [...previous, ...page.items]);
      setNextRank(page.next_after_rank);
      setRequestRank(null);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load ranked candidates.");
    });
    return () => { active = false; };
  }, [campaign.ranking_run_id, requestRank]);

  useEffect(() => {
    if (!idsKey) { setContacts([]); return; }
    let active = true;
    batchApi.contacts(idsKey.split("|"), token).then((items) => {
      if (!active) return;
      setContacts(items);
      setEmails((previous) => Object.fromEntries(items.map((item) =>
        [item.candidate_id, previous[item.candidate_id] ?? item.email ?? ""])));
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not check recipients.");
    });
    return () => { active = false; };
  }, [idsKey, token]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function saveContact(id: string) {
    setBusy(true);
    try {
      await batchApi.setContact(id, emails[id]?.trim() ?? "", token);
      setContacts(await batchApi.contacts(ids, token));
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save contact."); }
    finally { setBusy(false); }
  }

  async function save() {
    setBusy(true);
    try {
      const updated = await batchApi.edit(campaign.id, campaign.revision, ids, message, token);
      setError(null);
      onSaved(updated);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save batch."); }
    finally { setBusy(false); }
  }

  const byId = new Map(contacts.map((item) => [item.candidate_id, item]));
  const ready = ids.length > 0 && ids.every((id) => byId.get(id)?.contactable && byId.get(id)?.email);
  const changed = ids.some((id) => (emails[id] ?? "").trim() !== (byId.get(id)?.email ?? ""));
  const validMessage = message.split("{screening_link}").length === 2;
  return <div className="batch-section" aria-label="Edit proposed screening batch">
    <h3>Edit final recipients</h3>
    <p className="hint">Select candidates from this saved ranking run. Save the final list before approval.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="recipient-list">{candidates.map((candidate) => <label key={candidate.candidate_id}>
      <input type="checkbox" checked={selected.has(candidate.candidate_id)}
        onChange={() => toggle(candidate.candidate_id)} /> #{candidate.rank} {candidate.candidate_id}
    </label>)}</div>
    {nextRank !== null && <button type="button" className="secondary-button"
      onClick={() => setRequestRank(nextRank)}>Load more ranked candidates</button>}
    <p>{ids.length} selected for this campaign</p>
    {ids.map((id) => <div className="batch-contact" key={id}>
      <strong>{id}</strong>
      <input aria-label={`Email for ${id}`} type="email" value={emails[id] ?? ""}
        onChange={(event) => setEmails({ ...emails, [id]: event.target.value })} placeholder="Candidate email" />
      <button type="button" className="secondary-button" disabled={busy || !emails[id]}
        onClick={() => saveContact(id)}>Save contact</button>
      <span>{byId.get(id)?.contactable ? "Contactable" : "Contact needed"}</span>
    </div>)}
    <label>Invitation message <textarea rows={3} value={message}
      onChange={(event) => setMessage(event.target.value)} /></label>
    <div className="wizard-actions">
      <button type="button" disabled={busy || !ready || changed || !validMessage} onClick={save}>Save final list</button>
      <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Cancel edits</button>
    </div>
    {!ready && <p className="hint">Every selected candidate needs a saved, contactable email.</p>}
    {changed && <p className="hint">Save edited email addresses before saving the batch.</p>}
  </div>;
}
