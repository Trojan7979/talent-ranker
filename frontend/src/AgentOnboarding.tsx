import { FormEvent, useEffect, useState } from "react";
import { agentApi } from "./agentApi";
import type { AgentSession } from "./agentApi";
import { useRecruiterSession } from "./RecruiterLayout";
import "./agentOnboarding.css";

type Props = {
  initialMode: "new" | "existing";
  selectedActionLabel?: string;
  onConnected: (session: AgentSession, token: string) => void;
};

export function AgentOnboarding({ initialMode, selectedActionLabel, onConnected }: Props) {
  const recruiter = useRecruiterSession();
  const token = recruiter.token;
  const [jobId, setJobId] = useState("");
  const [jobs, setJobs] = useState<string[]>([]);
  const [mode, setMode] = useState(initialMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token.trim()) { setJobs([]); return; }
    let active = true;
    const timer = window.setTimeout(() => {
      agentApi.availableJobs(token.trim()).then(({ job_ids }) => {
        if (!active) return;
        setJobs(job_ids);
        setJobId((current) => job_ids.includes(current) ? current : job_ids[0] ?? "");
      }).catch(() => { if (active) setJobs([]); });
    }, 350);
    return () => { active = false; window.clearTimeout(timer); };
  }, [token]);

  async function connect(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await agentApi.createSession(jobId, token.trim(), undefined, mode === "existing");
      onConnected(created, token.trim());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start agent session."); }
    finally { setBusy(false); }
  }

  return <>
    <div className="agent-onboarding">
      <div className="agent-welcome">
        <p className="agent-speaker">Recruitment Agent</p>
        <h2>What would you like to accomplish?</h2>
        <p>Start with your resumes, then tell me about the role. I will guide you through criteria, ranking, evidence, and screening in chat.</p>
        <ol className="agent-start-steps">
          <li><strong>Connect resumes</strong><span>Choose a configured Drive or SharePoint file or folder, review the matches, and approve indexing.</span><a href="/sources">Open resume sources</a></li>
          <li><strong>Choose a role</strong><span>Select one of your assigned jobs here. Start a new conversation or open a saved shortlist.</span></li>
          <li><strong>Work in chat</strong><span>Ask for a JD, candidate comparison, or screening draft. I will ask before ranking or sending invitations.</span></li>
        </ol>
        {selectedActionLabel && <p className="agent-selected-action">Selected: {selectedActionLabel}. Open chat to review the request.</p>}
      </div>
      <div className="agent-connect-card">
        <div><strong>Your workspace</strong><p>Choose a role assigned to your signed-in account.</p></div>
        {error && <p className="agent-error" role="alert">{error}</p>}
        <div className="agent-setup-tabs" role="group" aria-label="Choose how to start">
          <button type="button" aria-pressed={mode === "new"} onClick={() => setMode("new")}>Start a conversation</button>
          <button type="button" aria-pressed={mode === "existing"} onClick={() => setMode("existing")}>Use latest saved run</button>
        </div>
        <form onSubmit={connect} className="agent-existing-run-form">
          <label>Role<select value={jobId} onChange={(event) => setJobId(event.target.value)} required disabled={!jobs.length}>
            {jobs.length ? jobs.map((id) => <option key={id} value={id}>{id}</option>) : <option value="">No assigned roles</option>}
          </select><span className="hint">{mode === "new"
            ? "The agent will ask for the job description and hiring criteria in chat."
            : "Opens the latest saved shortlist for this role."}</span></label>
          <button disabled={busy || !token.trim() || !jobId}>{busy ? "Connecting…" : "Open chat"}</button>
        </form>
      </div>
    </div>
    <div className="agent-composer agent-composer-disabled"><span>Ask about candidates or a hiring role…</span><button disabled aria-label="Send">↑</button></div>
  </>;
}
