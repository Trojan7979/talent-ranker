import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { agentApi } from "./agentApi";
import type { AgentSession, Campaign } from "./agentApi";
import { useRecruiterSession } from "./RecruiterLayout";

export function RecruitmentAgentPage() {
  const recruiter = useRecruiterSession();
  const [params, setParams] = useSearchParams();
  const [token, setToken] = useState(recruiter.token);
  const [jobId, setJobId] = useState("SENIOR_AI_ENGINEER_001");
  const [session, setSession] = useState<AgentSession | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [message, setMessage] = useState("Find the top 4 candidates and prepare a screening campaign.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sessionId = params.get("session");
    if (!sessionId || !recruiter.token) return;
    agentApi.getSession(sessionId, recruiter.token).then((restored) => {
      setSession(restored); setCampaign(restored.campaign);
    }).catch((cause: unknown) => setError(
      cause instanceof Error ? cause.message : "Could not restore the agent session."));
  }, [params, recruiter.token]);

  useEffect(() => {
    if (!session || campaign?.status !== "approved" || !recruiter.token) return;
    const interval = window.setInterval(() => {
      agentApi.getSession(session.id, recruiter.token).then((restored) => {
        setSession(restored); setCampaign(restored.campaign);
      }).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [session?.id, campaign?.status, recruiter.token]);

  async function connect(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await agentApi.createSession(jobId.trim(), token.trim());
      recruiter.setToken(token.trim()); setSession(created); setParams({ session: created.id });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start agent session."); }
    finally { setBusy(false); }
  }

  async function send(event: FormEvent) {
    event.preventDefault(); if (!session || !message.trim()) return;
    setBusy(true); setError(null);
    try {
      const response = await agentApi.send(session.id, message.trim(), recruiter.token);
      setSession(response.session); setCampaign(response.campaign); setMessage("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent execution failed."); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!session || !campaign) return;
    if (!window.confirm(`Approve this campaign and queue ${campaign.recipients.length} invitations?`)) return;
    setBusy(true); setError(null);
    try {
      const response = await agentApi.approve(session.id, campaign.revision, recruiter.token);
      setCampaign(response.campaign);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Approval failed."); }
    finally { setBusy(false); }
  }

  if (!session) return <main className="agent-page"><section className="agent-panel">
    <p className="agent-eyebrow">Agent Workforce</p><h1>Recruitment Agent</h1>
    <p className="hint">Start a persistent workspace against an existing saved ranking run.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form onSubmit={connect} className="agent-start">
      <label>Recruiter token<input type="password" value={token} onChange={(e) => setToken(e.target.value)} required /></label>
      <label>Job ID<input value={jobId} onChange={(e) => setJobId(e.target.value)} required /></label>
      <button disabled={busy}>Start workspace</button>
    </form>
  </section></main>;

  return <main className="agent-page"><section className="agent-panel">
    <div className="agent-heading"><div><p className="agent-eyebrow">Available</p><h1>Recruitment Agent</h1>
      <p className="hint">{session.job_id} · saved run {session.ranking_run_id}</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="agent-thread">
      {session.messages.length === 0 && <p className="hint">Ask the agent to find candidates or prepare a campaign.</p>}
      {session.messages.map((item) => <article key={item.id} className={`agent-message ${item.role}`}>
        <strong>{item.role === "user" ? "Recruiter" : "Recruitment Agent"}</strong><p>{item.content}</p>
      </article>)}
    </div>
    {campaign && <section className="agent-approval">
      <div><strong>Screening campaign</strong><span className={`agent-status ${campaign.status}`}>{campaign.status}</span></div>
      <p>{campaign.proposed_candidate_ids.length} recipients · expires in {campaign.expiry_hours} hours</p>
      <ul>{campaign.recipients.map((recipient) => <li key={recipient.candidate_id}>
        {recipient.display_name ?? recipient.candidate_id} · {recipient.email ?? "Contact missing"}
      </li>)}</ul>
      {campaign.questions?.must_haves.length ? <><strong>Screening questions</strong><ul>
        {campaign.questions.must_haves.map((question) => <li key={question.id}>{question.text}</li>)}
      </ul></> : null}
      <p className="hint">{campaign.message_template}</p>
      <p className="hint">Sender: {campaign.sender.email ?? campaign.sender.backend}</p>
      {campaign.status === "proposed" && <button disabled={busy} onClick={approve}>Approve and queue invitations</button>}
      {campaign.status === "approved" && <div role="status">
        <p>Approved. The existing delivery worker owns invitation delivery.</p>
        <ul>{Object.entries(campaign.delivery.counts).map(([status, count]) =>
          <li key={status}>{status}: {count}</li>)}</ul>
      </div>}
    </section>}
    <form onSubmit={send} className="agent-composer"><input value={message} onChange={(e) => setMessage(e.target.value)}
      placeholder="Ask about candidates or a hiring role…" disabled={busy} /><button disabled={busy || !message.trim()}>{busy ? "Working…" : "Send"}</button></form>
  </section></main>;
}
