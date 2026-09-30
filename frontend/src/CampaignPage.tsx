import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { screeningApi } from "./screeningApi";
import type { ActivityPage, Campaign, ReviewPage } from "./screeningApi";
import { CampaignEditor } from "./CampaignEditor";
import { batchApi } from "./batchApi";
import type { ContactPreview } from "./batchApi";
import { GmailConnection } from "./GmailConnection";
import { CompletedScreenings } from "./CompletedScreenings";
import { formatDateTime } from "./candidateDate";

export function CampaignPage() {
  const { campaignId } = useParams();
  const [token, setToken] = useState("");
  const [activeToken, setActiveToken] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [results, setResults] = useState<ReviewPage | null>(null);
  const [activity, setActivity] = useState<ActivityPage | null>(null);
  const [recipientContacts, setRecipientContacts] = useState<ContactPreview[]>([]);
  const [verifiedUrl, setVerifiedUrl] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState(false);
  const [questionLabels, setQuestionLabels] = useState<Record<string, string>>({});
  const loadedConfig = useRef<string | null>(null);

  const refresh = useCallback(async (auth: string) => {
    if (!campaignId) return;
    const [current, completed, roster] = await Promise.all([
      screeningApi.getCampaign(campaignId, auth),
      screeningApi.getResults(campaignId, auth),
      screeningApi.getActivity(campaignId, auth),
    ]);
    const contacts = current.status === "proposed"
      ? await batchApi.contacts(current.final_candidate_ids ?? current.proposed_candidate_ids, auth) : [];
    const version = completed.items[0]?.config_version;
    const configKey = version ? `${current.job_id}:${version}` : null;
    if (configKey && configKey !== loadedConfig.current) {
      const config = await batchApi.configVersion(current.job_id, version, auth);
      setQuestionLabels(Object.fromEntries(config.questions.must_haves.map((item) => [item.id, item.text])));
      loadedConfig.current = configKey;
    }
    setCampaign(current);
    setResults(completed);
    setActivity(roster);
    setRecipientContacts(contacts);
    setLastUpdated(new Date());
  }, [campaignId]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await refresh(token.trim());
      setActiveToken(token.trim());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not open campaign.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!activeToken) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        refresh(activeToken).catch((cause: unknown) =>
          setError(cause instanceof Error ? cause.message : "Refresh failed."));
      }
    }, 10000);
    return () => window.clearInterval(interval);
  }, [activeToken, refresh]);

  async function approve() {
    if (!campaign || !campaignId || !verifiedUrl || !recipientsReady) return;
    if (!window.confirm(`Approve ${campaign.final_candidate_ids?.length ?? campaign.proposed_candidate_ids.length} recipients and queue their links?`)) return;
    setBusy(true);
    let approved = false;
    try {
      setCampaign(await screeningApi.approveCampaign(campaignId, campaign.revision, activeToken));
      approved = true;
      try {
        await screeningApi.dispatchCampaign(campaignId, activeToken);
        setNotice("Email delivery requested. Invitation activity will update shortly.");
        setError(null);
      } catch (cause) {
        setError(`Batch approved and links queued, but sending could not start: ${cause instanceof Error ? cause.message : "unknown error"}. Use the delivery button to retry.`);
      }
      await refresh(activeToken);
    } catch (cause) {
      setError(`${approved ? "Batch approved, but refresh failed" : "Approval failed"}: ${cause instanceof Error ? cause.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function dispatchQueued() {
    if (!campaignId || !window.confirm("Request delivery of the queued invitations in this approved campaign?")) return;
    setBusy(true);
    try {
      await screeningApi.dispatchCampaign(campaignId, activeToken);
      setNotice("Email delivery requested. Invitation activity will update shortly.");
      setError(null);
      await refresh(activeToken);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not request delivery.");
    } finally { setBusy(false); }
  }

  async function exportCandidates(candidateIds: string[]) {
    if (!campaignId || candidateIds.length === 0) return;
    setBusy(true);
    try {
      const blob = await screeningApi.exportResults(campaignId, candidateIds, activeToken);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `screening-${campaignId}.xlsx`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Export failed.");
    } finally { setBusy(false); }
  }

  function toggleSelected(candidateId: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }

  const finalIds = campaign?.final_candidate_ids ?? campaign?.proposed_candidate_ids ?? [];
  const contactById = new Map(recipientContacts.map((item) => [item.candidate_id, item]));
  const recipientsReady = finalIds.length > 0 && finalIds.every((id) =>
    contactById.get(id)?.contactable && contactById.get(id)?.email);
  return (
    <main className="screening-page">
      <header className="screening-header">
        <Link to="/ranking">Ranking workspace</Link>
        <h1>Screening campaign</h1>
        <p className="hint">Campaign {campaignId}</p>
      </header>
      {!activeToken && (
        <form onSubmit={connect} className="screening-panel">
          <h2>Recruiter access</h2>
          <label>Bearer token
            <input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} required />
          </label>
          <button disabled={busy}>Open campaign</button>
          <p className="hint">The token stays in this browser tab's memory.</p>
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {campaign && (
        <>
          {activeToken && campaignId && <GmailConnection campaignId={campaignId} recruiterToken={activeToken} />}
          <section className="screening-panel">
            <div className="screening-title-row">
              <div>
                <h2>{campaign.job_id}</h2>
                <p>Decision: <strong>{campaign.status}</strong> · Revision {campaign.revision}</p>
              </div>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => refresh(activeToken).catch((cause: unknown) => setError(String(cause)))}>Refresh</button>
            </div>
            <p>Final recipients ({finalIds.length})</p>
            <div className="recipient-list">{finalIds.map((id) => <span key={id}>{id}
              {campaign.status === "proposed" && <small> {contactById.get(id)?.email ?? "Contact needed"}</small>}
            </span>)}</div>
            <p className="hint">Proposed top-ranked IDs: {campaign.proposed_candidate_ids.join(", ")}</p>
            <p>Invitation message: {campaign.message_template}</p>
            <p>Link expiry: {campaign.expiry_hours} hours</p>
            {campaign.status === "proposed" && !editing && <button type="button" className="secondary-button"
              onClick={() => setEditing(true)}>Edit final recipients and message</button>}
            {campaign.status === "proposed" && editing && <CampaignEditor campaign={campaign} token={activeToken}
              onCancel={() => setEditing(false)} onSaved={(updated) => {
                setCampaign(updated);
                setEditing(false);
                refresh(activeToken).catch((cause: unknown) => setError(String(cause)));
              }} />}
            {campaign.status === "proposed" && !editing && (
              <div className="approval-box">
                {!recipientsReady && <p className="error">Every final recipient needs a saved, contactable email.</p>}
                <label className="inline-check">
                  <input type="checkbox" checked={verifiedUrl} onChange={(event) => setVerifiedUrl(event.target.checked)} />
                  I verified the final recipients and the server's screening link URL opens this app's /s page.
                </label>
                <button type="button" disabled={!verifiedUrl || !recipientsReady || busy} onClick={approve}>Approve batch and queue links</button>
                <p className="hint">Approval queues links and requests delivery from the configured backend sender.</p>
              </div>
            )}
            {campaign.status === "approved" && <p role="status">Batch approved. Delivery state appears below.</p>}
          </section>
          <section className="screening-panel">
            <h2>Invitation activity</h2>
            <p className="hint">Queued means approved but not yet accepted by the email provider. Sent means provider accepted the message.</p>
            {campaign.status === "approved" && activity?.items.some((item) => item.delivery_status === "pending" || item.delivery_status === "failed") &&
              <button type="button" className="secondary-button" disabled={busy} onClick={dispatchQueued}>Request delivery for queued invitations</button>}
            <div className="shortlist-grid">
              {activity?.items.map((item) => (
                <article className="result-card" key={item.invite_id}>
                  <div><h3>{item.candidate_id}</h3><span>{item.recipient_email}</span></div>
                  <strong>{item.status ?? "Queued"}</strong>
                  <p>Delivery: {item.delivery_status}</p>
                  {item.opened_at && <p>Opened: {formatDateTime(item.opened_at)}</p>}
                  {item.started_at && <p>Started: {formatDateTime(item.started_at)}</p>}
                  {item.completed_at && <p>Completed: {formatDateTime(item.completed_at)}</p>}
                </article>
              ))}
            </div>
            {activity?.items.length === 0 && <p>No invitations have been queued yet.</p>}
            {activity?.next_cursor && <p className="hint">Showing the first 200 invitations.</p>}
          </section>
          <CompletedScreenings results={results} selected={selected} busy={busy}
            lastUpdated={lastUpdated} labels={questionLabels} onToggle={toggleSelected}
            onExport={exportCandidates} onSelectAll={() => {
              const ids = results?.items.map((item) => item.candidate_id) ?? [];
              setSelected((current) => ids.every((id) => current.has(id)) ? new Set() : new Set(ids));
            }} />
        </>
      )}
    </main>
  );
}
