import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCampaigns } from "./campaignDirectoryApi";
import type { CampaignCursor, CampaignSummary } from "./campaignDirectoryApi";
import { useRecruiterSession } from "./RecruiterLayout";

export function CampaignsPage() {
  const recruiterSession = useRecruiterSession();
  const [tokenInput] = useState(recruiterSession.token);
  const [token, setToken] = useState(recruiterSession.token);
  const [jobInput, setJobInput] = useState("");
  const [jobFilter, setJobFilter] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CampaignCursor | null>(null);
  const [nextCursor, setNextCursor] = useState<CampaignCursor | null>(null);
  const [items, setItems] = useState<CampaignSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listCampaigns(token, jobFilter, cursor, controller.signal)
      .then((page) => {
        recruiterSession.setToken(token);
        setItems((previous) => cursor ? [...previous, ...page.items] : page.items);
        setNextCursor(page.next_before_created_at && page.next_before_id
          ? { createdAt: page.next_before_created_at, id: page.next_before_id }
          : null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load screening campaigns.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token, jobFilter, cursor, retry, recruiterSession.setToken]);

  function load(event: FormEvent) {
    event.preventDefault();
    setItems([]);
    setNextCursor(null);
    setCursor(null);
    setJobFilter(jobInput.trim() || null);
    setToken(tokenInput.trim());
    setRetry((value) => value + 1);
  }

  return (
    <main className="shortlist-workspace">
      <header className="shortlist-header">
        <h1>Screening campaigns</h1>
        <p>Find a proposed or approved campaign and continue the recruiter workflow.</p>
      </header>
      <form onSubmit={load}>
        <label htmlFor="campaign-job-filter">Filter by job ID</label>
        <input id="campaign-job-filter" value={jobInput}
          onChange={(event) => setJobInput(event.target.value)} placeholder="All jobs" />
        <button type="submit">Show campaigns</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {token && !loading && !error && items.length === 0 && <p>No campaigns found.</p>}
      <section className="shortlist-grid" aria-label="Saved campaigns">
        {items.map((campaign) => (
          <article key={campaign.id} className="result-card">
            <div>
              <h2>{campaign.job_id}</h2>
              <p>{campaign.status} · {campaign.candidate_count} candidates</p>
              <p><time dateTime={campaign.created_at}>
                {new Date(campaign.created_at).toLocaleString()}
              </time></p>
            </div>
            <Link to={`/screening/campaigns/${campaign.id}`}>Open campaign</Link>
          </article>
        ))}
      </section>
      {loading && <p role="status">Loading campaigns...</p>}
      {!loading && error && <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>}
      {!loading && !error && nextCursor &&
        <button type="button" onClick={() => setCursor(nextCursor)}>Load more</button>}
    </main>
  );
}
