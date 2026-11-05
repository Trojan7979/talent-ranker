import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRecruiterSession } from "./RecruiterLayout";
import { agentApi } from "./agentApi";
import type { DriveWatchInbox, DriveWatchSchedule } from "./agentApi";
import { sourceRequest } from "./sourceApi";
import { SourceProposalReview } from "./SourceProposalReview";
import { IndexingOutcomeSummary } from "./IndexingOutcomeSummary";
import { IndexingCompletionActions } from "./IndexingCompletionActions";
import type { Decision } from "./SourceProposalReview";
import { validId, type File, type Job, type SourceProvider } from "./sourceTypes";
import { selectFirstResumes } from "./sourceSelection";


export function ResumeSourcesPage() {
  const recruiterSession = useRecruiterSession();
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const [provider, setProvider] = useState<SourceProvider>(
    params.get("source") === "drive" ? "drive" : "sharepoint",
  );
  const [token] = useState(recruiterSession.token);
  const [driveConnected, setDriveConnected] = useState(false);
  const [driveConnectUrl, setDriveConnectUrl] = useState("");
  const [driveWatches, setDriveWatches] = useState<DriveWatchInbox["watches"]>([]);
  const [watchNotice, setWatchNotice] = useState<string | null>(null);
  const [watchSchedule, setWatchSchedule] = useState<DriveWatchSchedule>("instant");
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [folderUrl, setFolderUrl] = useState(params.get("location") ?? "");
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
    void sourceRequest<{ connected: boolean; connect_url: string }>("/drive/connection", token.trim())
      .then((value) => { if (active) { setDriveConnected(value.connected); setDriveConnectUrl(value.connect_url); } })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not check Drive connection.");
      });
    return () => { active = false; };
  }, [provider, token]);

  useEffect(() => {
    const saved = driveWatches.find((watch) => watch.folder_url === folderUrl.trim());
    if (saved) setWatchSchedule(saved.notification_schedule);
  }, [driveWatches, folderUrl]);

  useEffect(() => {
    if (provider !== "drive" || !token.trim()) return;
    let active = true;
    void agentApi.driveInbox(token.trim()).then((inbox) => {
      if (active) setDriveWatches(inbox.watches);
    }).catch(() => undefined);
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
      if (provider === "s3") throw new Error("S3 intake is not connected yet.");
      const pendingAlerts = provider === "drive"
        ? await agentApi.driveInbox(token.trim()).then((inbox) => inbox.alerts).catch(() => [])
        : [];
      const result = await sourceRequest<{ folder_url: string; files: File[] }>(`/${provider}/preview`, token.trim(), {
        [provider === "drive" ? "location" : "folder_url"]: folderUrl.trim(),
      }, AbortSignal.timeout(20000));
      setFolder(result.folder_url); setFiles(result.files); setJob(null); setParams({});
      recruiterSession.setToken(token.trim());
      requestId.current = null; preparedReview.current = null;
      const reviewedAlerts = pendingAlerts.filter((alert) => alert.folder_url === result.folder_url);
      const acknowledgements = await Promise.allSettled(
        reviewedAlerts.map((alert) => agentApi.dismissDriveAlert(alert.id, token.trim())),
      );
      if (acknowledgements.some((outcome) => outcome.status === "rejected")) {
        setError("Resumes were previewed, but some alerts could not be cleared. Please retry.");
      }
    } catch (cause) {
      setError(cause instanceof Error && cause.name === "TimeoutError"
        ? "Source preview timed out. Please try again."
        : cause instanceof Error ? cause.message : "Could not verify source.");
    } finally { setBusy(false); setBusyMessage(""); }
  }

  function connectDrive() {
    if (!driveConnectUrl) { setError("Could not start Google Drive connection."); return; }
    window.location.assign(driveConnectUrl);
  }

  async function watchDrive() {
    setBusy(true); setBusyMessage("Saving Drive folder…"); setError(null); setWatchNotice(null);
    try {
      await agentApi.watchDrive(folderUrl.trim(), watchSchedule, timeZone, token.trim());
      const inbox = await agentApi.driveInbox(token.trim());
      setDriveWatches(inbox.watches);
      recruiterSession.setToken(token.trim());
      setWatchNotice("Folder saved. The watcher will check it on your selected schedule while the worker is running.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not watch Drive folder.");
    } finally { setBusy(false); setBusyMessage(""); }
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

  function selectFirst(count: number) {
    if (!job || job.status !== "awaiting_review") return;
    setDecisions((current) => selectFirstResumes(job.proposals, current, count));
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
      <p>Choose a resume source, preview its PDF and DOCX files, then review candidate matches before indexing.</p>
      <form onSubmit={verify}>
        <label>Resume source<select value={provider} onChange={(event) => {
          setProvider(event.target.value as SourceProvider);
          setFolderUrl(""); setFolder(""); setFiles([]); setJob(null); setParams({});
          requestId.current = null; preparedReview.current = null;
        }}><option value="sharepoint">SharePoint</option><option value="drive">Google Drive</option><option value="s3">Amazon S3</option></select></label>
        <label>{provider === "drive" ? "Google Drive file or folder link" : provider === "s3" ? "S3 bucket and prefix" : "SharePoint folder link"}
          <input type={provider === "s3" ? "text" : "url"} value={folderUrl}
            placeholder={provider === "drive" ? "https://drive.google.com/drive/folders/..."
              : provider === "s3" ? "s3://bucket/incoming/resumes/" : "https://tenant.sharepoint.com/sites/..."}
            onChange={(event) => { setFolderUrl(event.target.value); setFolder(""); }} required /></label>
        <button disabled={busy || !token.trim() || !folderUrl.trim() || provider === "s3" || (provider === "drive" && !driveConnected)}>Preview resumes</button>
      </form>
      {provider === "drive" && <div>
        <p role="status">Google Drive: {driveConnected ? "connected" : "connection required"}</p>
        <button type="button" disabled={busy || !token.trim() || !driveConnectUrl}
          onClick={connectDrive}>{driveConnected ? "Reconnect Google Drive" : "Connect Google Drive"}</button>
        <p>For ongoing intake, save a folder link above. New resumes will be flagged in the agent chat.</p>
        <label>Check for new resumes
          <select value={watchSchedule} onChange={(event) => setWatchSchedule(event.target.value as DriveWatchSchedule)}>
            <option value="instant">Immediately (checks every 2 seconds)</option>
            <option value="daily">Every day at 6:00 p.m.</option>
            <option value="weekends">Saturday and Sunday at 6:00 p.m.</option>
          </select>
        </label>
        <p>Scheduled checks use your time zone ({timeZone}). Alerts appear after the next check.</p>
        <button type="button" disabled={busy || !driveConnected || !token.trim() || !folderUrl.includes("/folders/")}
          onClick={watchDrive}>Save notification schedule</button>
        {watchNotice && <p role="status">{watchNotice}</p>}
        {driveWatches.length > 0 && <div>
          <strong>Saved intake folders</strong>
          <ul className="source-watch-list">{driveWatches.map((watch) => <li key={watch.id}>
            {watch.folder_url} · {watch.notification_schedule} · next check {new Date(watch.next_scan_at).toLocaleString()}
            {watch.last_error ? ` · ${watch.last_error}` : ""}
          </li>)}</ul>
        </div>}
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
        <p role="status">{job.status.replaceAll("_", " ")}.</p>
        <IndexingOutcomeSummary job={job} />
        <IndexingCompletionActions job={job} />
        <SourceProposalReview review={review} decisions={decisions} update={update}
          busy={busy} canApprove={canApprove} approve={approve} selectFirst={selectFirst} />
        {job.failures.length > 0 && <ul>{job.failures.map((failure, index) =>
          <li key={`${index}-${failure}`}>{failure}</li>)}</ul>}
      </>}
    </section>}
  </main>;
}
