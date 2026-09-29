import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listSavedRuns } from "./api";
import type { SavedRunCursor, SavedRunSummary } from "./api";

export function SavedRunsPage() {
  const [jobInput, setJobInput] = useState("");
  const [jobFilter, setJobFilter] = useState<string | null>(null);
  const [cursor, setCursor] = useState<SavedRunCursor | null>(null);
  const [nextCursor, setNextCursor] = useState<SavedRunCursor | null>(null);
  const [items, setItems] = useState<SavedRunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listSavedRuns(jobFilter, cursor, controller.signal)
      .then((page) => {
        setItems((previous) => cursor ? [...previous, ...page.items] : page.items);
        setNextCursor(page.next_before_created_at && page.next_before_run_id
          ? { createdAt: page.next_before_created_at, runId: page.next_before_run_id }
          : null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load saved shortlists.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [jobFilter, cursor, retry]);

  function applyFilter(event: FormEvent) {
    event.preventDefault();
    setItems([]);
    setNextCursor(null);
    setCursor(null);
    setJobFilter(jobInput.trim() || null);
    setRetry((value) => value + 1);
  }

  return (
    <main className="shortlist-workspace">
      <header className="shortlist-header">
        <h1>Saved shortlists</h1>
        <p>Open a previous ranking run to review candidates or prepare a screening batch.</p>
      </header>
      <form onSubmit={applyFilter}>
        <label htmlFor="shortlist-job-filter">Filter by job ID</label>
        <input id="shortlist-job-filter" value={jobInput}
          onChange={(event) => setJobInput(event.target.value)} placeholder="All jobs" />
        <button type="submit">Apply filter</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {!loading && !error && items.length === 0 && <p>No saved shortlists found.</p>}
      <section className="shortlist-grid" aria-label="Saved ranking runs">
        {items.map((run) => (
          <article key={run.run_id} className="result-card">
            <div>
              <h2>{run.job_id}</h2>
              <p><time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></p>
              <p>{run.total_count} candidates</p>
            </div>
            <Link to={`/jobs/${encodeURIComponent(run.job_id)}/ranking-runs/${run.run_id}`}>
              Open shortlist
            </Link>
          </article>
        ))}
      </section>
      {loading && <p role="status">Loading saved shortlists...</p>}
      {!loading && error && <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>}
      {!loading && !error && nextCursor &&
        <button type="button" onClick={() => setCursor(nextCursor)}>Load more</button>}
    </main>
  );
}
