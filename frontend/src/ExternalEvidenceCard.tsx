import { useEffect, useRef, useState } from "react";
import { sourceRequest } from "./sourceApi";

type Evidence = {
  url: string;
  status: "pending" | "running" | "completed" | "failed" | "blocked" | "unsupported";
  evidence: { text?: string };
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
      {loading ? "Loading links…" : items ? "Refresh links" : "View resume links"}
    </button>
    {error && <p className="error" role="alert">{error}</p>}
    {items && <>
      {!items.length && <p>No links recorded. Previously indexed resumes need re-indexing to collect links.</p>}
      {items.map((item) => <div key={item.url}>
        <a href={item.url} target="_blank" rel="noopener noreferrer">{new URL(item.url).hostname}</a>
        {item.status === "completed" && item.evidence.text && <details>
          <summary>View fetched evidence</summary>
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.evidence.text}</p>
        </details>}
      </div>)}
    </>}
  </div>;
}
