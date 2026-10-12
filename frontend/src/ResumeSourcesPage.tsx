import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRecruiterSession } from "./RecruiterLayout";
import { sourceRequest } from "./sourceApi";

type File = { file_id: string; name: string; web_url: string };
type Proposal = {
  object_id: string; file_name: string; name: string | null; email: string | null;
  candidate_id: string | null; suggestion: "existing" | "new" | "review";
  analysis_error: string | null;
  job_title: string | null; web_url: string;
};
type Job = {
  id: string; status: string; discovered: number; indexed: number;
  skipped: number; failures: string[]; proposals: Proposal[];
};
type Decision = {
  object_id: string; action: "existing" | "new" | "skip";
  candidate_id: string; name: string; email: string; job_title: string;
};
const validId = /^CAND_(?:[0-8]\d{3}|9000)$/;

export function ResumeSourcesPage() {
  const recruiterSession = useRecruiterSession();
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const [provider, setProvider] = useState<"sharepoint" | "drive">(
    params.get("source") === "drive" ? "drive" : "sharepoint",
  );
  const [token, setToken] = useState(recruiterSession.token);
  const [driveConnected, setDriveConnected] = useState(false);
  const [folderUrl, setFolderUrl] = useState("");
  const [folder, setFolder] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState(false);
  const [busyMessage, setBusyMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef<string | null>(null);
  const preparedReview = useRef<string | null>(null);

  useEffect(() => {
    if (provider !== "drive" || !token.trim()) return;
    let active = true;
    void sourceRequest<{ connected: boolean }>("/drive/connection", token.trim())
      .then((value) => { if (active) setDriveConnected(value.connected); })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not check Drive connection.");
      });
    return () => { active = false; };
  }, [provider, token]);

  useEffect(() => {
    if (!jobId || !token.trim()) return;
    let active = true;
    const refresh = () => sourceRequest<Job>(`/${provider}/jobs/${encodeURIComponent(jobId)}`, token.trim())
      .then((result) => { if (active) { setJob(result); setError(null); } })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load job.");
      });
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [jobId, provider, token]);

  useEffect(() => {
    if (!job || job.status !== "awaiting_review" || preparedReview.current === job.id) return;
    setDecisions(Object.fromEntries(job.proposals.map((item) => [item.object_id, {
      object_id: item.object_id,
      action: item.suggestion === "review" ? "skip" : item.suggestion,
      candidate_id: item.candidate_id ?? "", name: item.name ?? "", email: item.email ?? "",
      job_title: item.job_title ?? "",
    }])));
    preparedReview.current = job.id;
  }, [job]);

  async function verify(event: FormEvent) {
    event.preventDefault(); setBusy(true); setBusyMessage("Checking the source file…"); setError(null);
    try {
      const result = await sourceRequest<{ folder_url: string; files: File[] }>(`/${provider}/preview`, token.trim(), {
        [provider === "drive" ? "location" : "folder_url"]: folderUrl.trim(),
      }, AbortSignal.timeout(20000));
      setFolder(result.folder_url); setFiles(result.files); setJob(null); setParams({});
      recruiterSession.setToken(token.trim());
      requestId.current = null; preparedReview.current = null;
    } catch (cause) {
      setError(cause instanceof Error && cause.name === "TimeoutError"
        ? "Source preview timed out. Please try again."
        : cause instanceof Error ? cause.message : "Could not verify source.");
    } finally { setBusy(false); setBusyMessage(""); }
  }

  async function connectDrive() {
    setBusy(true); setBusyMessage("Starting Google sign-in…"); setError(null);
    try {
      recruiterSession.setToken(token.trim());
      const result = await sourceRequest<{ authorization_url: string }>(
        "/drive/connect", token.trim(), {},
      );
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not connect Google Drive.");
      setBusy(false); setBusyMessage("");
    }
  }

  async function analyze() {
    setBusy(true); setError(null);
    try {
      requestId.current ??= crypto.randomUUID();
      const result = await sourceRequest<Job>(`/${provider}/analyze`, token.trim(), {
        [provider === "drive" ? "location" : "folder_url"]: folder,
        request_id: requestId.current,
      });
      setJob(result); setParams({ job: result.id, source: provider });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start analysis.");
    } finally { setBusy(false); }
  }

  function update(objectId: string, change: Partial<Decision>) {
    setDecisions((current) => ({ ...current, [objectId]: { ...current[objectId], ...change } }));
  }

  const review = job?.status === "awaiting_review" ? job.proposals : [];
  const chosen = review.map((item) => decisions[item.object_id]).filter(Boolean);
  const existingIds = chosen.filter((item) => item.action === "existing")
    .map((item) => item.candidate_id.trim().toUpperCase());
  const canApprove = chosen.length === review.length && chosen.some((item) => item.action !== "skip")
    && existingIds.every((id) => validId.test(id))
    && new Set(existingIds).size === existingIds.length;

  async function approve() {
    if (!job || !canApprove) return;
    setBusy(true); setError(null);
    try {
      const result = await sourceRequest<Job>(`/${provider}/jobs/${job.id}/approve`, token.trim(), {
        decisions: chosen.map((item) => ({
          ...item, candidate_id: item.candidate_id.trim().toUpperCase(),
        })),
      });
      setJob(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not approve indexing.");
    } finally { setBusy(false); }
  }

  return <main className="screening-page">
    <section className="screening-panel">
      <h1>Resume sources</h1>
      <p>Choose an authorized source, preview its PDF and DOCX resumes, then review candidate matches before indexing.</p>
      <p>{provider === "drive" ? "Paste one Drive file link for your resume, or a folder link for bulk intake." :
        "Original documents stay in SharePoint. Sieve saves reviewed details and searchable content."}</p>
      <form onSubmit={verify}>
        <label>Recruiter access token<input type="password" autoComplete="off" value={token}
          onChange={(event) => setToken(event.target.value)} required /></label>
        <label>Resume source<select value={provider} onChange={(event) => {
          setProvider(event.target.value as "sharepoint" | "drive");
          setFolderUrl(""); setFolder(""); setFiles([]); setJob(null); setParams({});
          requestId.current = null; preparedReview.current = null;
        }}><option value="sharepoint">SharePoint</option><option value="drive">Google Drive</option></select></label>
        <label>{provider === "drive" ? "Google Drive file or folder link" : "SharePoint folder link"}<input type="url" value={folderUrl}
          placeholder={provider === "drive" ? "https://drive.google.com/file/d/.../view" : "https://tenant.sharepoint.com/sites/..."}
          onChange={(event) => { setFolderUrl(event.target.value); setFolder(""); }} required /></label>
        <button disabled={busy || !token.trim() || !folderUrl.trim() || (provider === "drive" && !driveConnected)}>Preview resumes</button>
      </form>
      {provider === "drive" && <div>
        <p role="status">Google Drive: {driveConnected ? "connected" : "connection required"}</p>
        <button type="button" disabled={busy || !token.trim()}
          onClick={connectDrive}>{driveConnected ? "Reconnect Google Drive" : "Connect Google Drive"}</button>
      </div>}
      {busy && <p role="status">{busyMessage || "Working…"}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
    {folder && !jobId && <section className="screening-panel">
      <h2>Source preview</h2>
      <p>{files.length} PDF or DOCX resumes found. Analysis checks identity; it does not index yet.</p>
      <div className="source-file-list">{files.map((file) =>
        <div className="source-file" key={file.file_id}>{file.name}
          {file.web_url && <a href={file.web_url} target="_blank" rel="noopener noreferrer">Open source</a>}
        </div>)}</div>
      <button type="button" disabled={busy || !files.length} onClick={analyze}>Analyze resumes</button>
    </section>}
    {jobId && <section className="screening-panel">
      <h2>{provider === "drive" ? "Google Drive" : "SharePoint"} job</h2>
      {!token.trim() && <p>Enter recruiter access above to load this job.</p>}
      {job && <>
        <p role="status">{job.status.replaceAll("_", " ")}: {job.indexed} indexed.</p>
        {review.length > 0 && <>
          <p>Confirm each suggestion. Uncertain files are skipped by default.</p>
          <div className="source-file-list">{review.map((item) => {
            const decision = decisions[item.object_id];
            return <div className="source-file" key={item.object_id}>
              <strong>{item.file_name}</strong>
              {item.web_url && <a href={item.web_url} target="_blank" rel="noopener noreferrer">Open source</a>}
              <span>{item.suggestion === "existing" ? `Existing: ${item.candidate_id}`
                : item.suggestion === "new" ? "New candidate" : "Needs review"}</span>
              {item.analysis_error && <span className="error">{item.analysis_error}</span>}
              {decision && <>
                <select aria-label={`Action for ${item.file_name}`} value={decision.action}
                  onChange={(event) => update(item.object_id, { action: event.target.value as Decision["action"] })}>
                  <option value="skip">Skip</option>
                  <option value="existing">Use existing candidate</option>
                  {item.suggestion === "new" && <option value="new">Create new candidate ID</option>}
                </select>
                {decision.action === "existing" && <input aria-label={`Candidate ID for ${item.file_name}`}
                  placeholder="CAND_0001" value={decision.candidate_id}
                  onChange={(event) => update(item.object_id, { candidate_id: event.target.value })} />}
                {decision.action !== "skip" && <>
                  <input aria-label={`Name for ${item.file_name}`} placeholder="Candidate name"
                    value={decision.name} onChange={(event) => update(item.object_id, { name: event.target.value })} />
                  <input aria-label={`Email for ${item.file_name}`} placeholder="Email (optional)"
                    value={decision.email} onChange={(event) => update(item.object_id, { email: event.target.value })} />
                  <input aria-label={`Job title for ${item.file_name}`} placeholder="Job title (optional)"
                    maxLength={120} value={decision.job_title}
                    onChange={(event) => update(item.object_id, { job_title: event.target.value })} />
                </>}
              </>}
            </div>;
          })}</div>
          <button type="button" disabled={busy || !canApprove} onClick={approve}>Confirm and index</button>
        </>}
        {job.status !== "awaiting_review" && <p>{job.discovered} resumes discovered; {job.skipped} skipped; {job.failures.length} failures.</p>}
        {job.failures.length > 0 && <ul>{job.failures.map((failure, index) =>
          <li key={`${index}-${failure}`}>{failure}</li>)}</ul>}
      </>}
    </section>}
  </main>;
}
