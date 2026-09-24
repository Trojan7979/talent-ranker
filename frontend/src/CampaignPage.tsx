import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { screeningApi } from "./screeningApi";
import type { Campaign, ReviewPage } from "./screeningApi";

const outcomeLabel = {
  proceed_to_interview: "Screening passed",
  needs_recruiter_review: "Needs recruiter review",
  do_not_proceed: "Do not proceed",
};

export function CampaignPage() {
  const { campaignId } = useParams();
  const [token, setToken] = useState("");
  const [activeToken, setActiveToken] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [results, setResults] = useState<ReviewPage | null>(null);
  const [verifiedUrl, setVerifiedUrl] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async (auth: string) => {
    if (!campaignId) return;
    const [current, completed] = await Promise.all([
      screeningApi.getCampaign(campaignId, auth),
      screeningApi.getResults(campaignId, auth),
    ]);
    setCampaign(current);
    setResults(completed);
    setLastUpdated(new Date());
    setError(null);
  }, [campaignId]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await refresh(token.trim());
      setActiveToken(token.trim());
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
    if (!campaign || !campaignId || !verifiedUrl) return;
    if (!window.confirm(`Approve ${campaign.final_candidate_ids?.length ?? campaign.proposed_candidate_ids.length} recipients and queue their links?`)) return;
    setBusy(true);
    try {
      setCampaign(await screeningApi.approveCampaign(campaignId, campaign.revision, activeToken));
      await refresh(activeToken);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval failed.");
    } finally {
      setBusy(false);
    }
  }

  const finalIds = campaign?.final_candidate_ids ?? campaign?.proposed_candidate_ids ?? [];
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
      {campaign && (
        <>
          <section className="screening-panel">
            <div className="screening-title-row">
              <div>
                <h2>{campaign.job_id}</h2>
                <p>Decision: <strong>{campaign.status}</strong> · Revision {campaign.revision}</p>
              </div>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => refresh(activeToken).catch((cause: unknown) => setError(String(cause)))}>Refresh</button>
            </div>
            <p>Final recipients ({finalIds.length})</p>
            <div className="recipient-list">{finalIds.map((id) => <span key={id}>{id}</span>)}</div>
            <p className="hint">Proposed top-ranked IDs: {campaign.proposed_candidate_ids.join(", ")}</p>
            <p>Invitation message: {campaign.message_template}</p>
            <p>Link expiry: {campaign.expiry_hours} hours</p>
            {campaign.status === "proposed" && (
              <div className="approval-box">
                <label className="inline-check">
                  <input type="checkbox" checked={verifiedUrl} onChange={(event) => setVerifiedUrl(event.target.checked)} />
                  I verified the final recipients and the server's screening link URL opens this app's /s page.
                </label>
                <button type="button" disabled={!verifiedUrl || busy} onClick={approve}>Approve batch and queue links</button>
                <p className="hint">Approval queues invitations; the backend dispatch command sends email separately.</p>
              </div>
            )}
            {campaign.status === "approved" && <p role="status">Batch approved. Invitations are queued for backend dispatch.</p>}
          </section>
          <section className="screening-panel">
            <h2>Completed screenings</h2>
            <p className="hint">Refreshes every 10 seconds while this tab is visible. {lastUpdated && `Last checked ${lastUpdated.toLocaleTimeString()}.`}</p>
            {results && <p>{results.counts.needs_recruiter_review} need review · {results.counts.proceed_to_interview} passed · {results.counts.do_not_proceed} do not proceed</p>}
            <div className="shortlist-grid">
              {results?.items.map((item) => (
                <article className="result-card" key={item.id}>
                  <div><h3>{item.candidate_id}</h3><strong>{outcomeLabel[item.outcome]}</strong></div>
                  <p>Confirmed: {item.confirmed.join(", ") || "None"}</p>
                  <p>Missing: {item.missing.join(", ") || "None"}</p>
                  <p>Verify: {item.needs_verification.join(", ") || "None"}</p>
                </article>
              ))}
            </div>
            {results?.items.length === 0 && <p>No completed screenings yet.</p>}
          </section>
        </>
      )}
    </main>
  );
}
