import { useEffect, useRef, useState } from "react";
import { sourceRequest } from "./sourceApi";
import type { ResumeSource } from "./sourceApi";

export function ResumeSourceCard({ candidateId, token }: { candidateId: string; token: string }) {
  const [source, setSource] = useState<ResumeSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    setSource(null);
    setError(null);
    setLoading(false);
    return () => { pending.current?.abort(); };
  }, [candidateId, token]);

  async function loadSource() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setSource(null);
    setError(null);
    try {
      const result = await sourceRequest<ResumeSource>(
        `/candidates/${encodeURIComponent(candidateId)}/resume`, token, undefined, controller.signal,
      );
      if (!controller.signal.aborted) setSource(result);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Could not load the source resume.");
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <div className="resume-source-card" aria-label={`Source resume for ${candidateId}`}>
    <button type="button" className="secondary-button" disabled={!token || loading} onClick={loadSource}>
      {loading ? "Checking source…" : source ? "Refresh source link" : "View resume"}
    </button>
    {!token && <small>Recruiter access is required to view the source.</small>}
    {error && <p className="error" role="alert">{error}</p>}
    {source && <>
      <a href={source.web_url} target="_blank" rel="noopener noreferrer">Open {source.file_name} in {source.provider === "google_drive" ? "Google Drive" : "SharePoint"}</a>
      <small>This opens the current document using your {source.provider === "google_drive" ? "Google Drive" : "SharePoint"} access.</small>
      {source.source_status === "changed" && <p role="status">
        The file or its details changed since indexing. Review and re-index to refresh the results.
      </p>}
      {source.source_status === "unknown" && <small>The indexed version could not be compared.</small>}
    </>}
  </div>;
}
