import { useEffect, useRef, useState } from "react";
import { sourceRequest } from "./sourceApi";

type Evidence = {
  url: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed" | "blocked" | "unsupported";
  fetched_at: string | null;
  evidence: { title?: string; text?: string };
};

const statusLabels: Record<Evidence["status"], string> = {
  pending: "Waiting for public check", running: "Checking public page", completed: "Fetched",
  failed: "Could not retrieve", blocked: "Access restricted", unsupported: "Link only",
};

export function ExternalEvidenceCard({ candidateId, token }: { candidateId: string; token: string }) {
  const [items, setItems] = useState<Evidence[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    setItems(null);
    setError(null);
    setLoading(false);
    return () => pending.current?.abort();
  }, [candidateId, token]);

  async function load() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    try {
      const result = await sourceRequest<Evidence[]>(
        `/candidates/${encodeURIComponent(candidateId)}/evidence`, token, undefined, controller.signal,
      );
      if (!controller.signal.aborted) setItems(result);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load evidence.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <div className="resume-source-card" aria-label={`Resume links for ${candidateId}`}>
    <button type="button" className="secondary-button" onClick={load} disabled={!token || loading}>
      {loading ? "Loading links…" : items ? "Refresh links and statuses" : "View resume links"}
    </button>
    {error && <p className="error" role="alert">{error}</p>}
    {items && <>
      <small>Links found in the resume. Opening a link does not verify ownership or change ranking scores.</small>
      {!items.length && <p>No links recorded. Previously indexed resumes need re-indexing to collect links.</p>}
      {items.map((item) => <details key={item.url}>
        <summary>{item.evidence.title || new URL(item.url).hostname} — {statusLabels[item.status]}</summary>
        <a href={item.url} target="_blank" rel="noopener noreferrer">
          {item.status === "unsupported" ? "Open profile or page" : "Open source"}
        </a>
        {item.status === "unsupported" && <small>Saved as a resume link; this app does not fetch or verify its content.</small>}
        {item.fetched_at && <small> Retrieved {new Date(item.fetched_at).toLocaleString()}</small>}
        {item.status === "completed" && <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.evidence.text}</p>}
      </details>)}
    </>}
  </div>;
}
