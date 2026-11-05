import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { agentApi } from "./agentApi";
import type { AgentSession, Campaign, DriveWatchInbox } from "./agentApi";
import { batchApi } from "./batchApi";
import { qualificationQuestion } from "./CandidateQuestion";
import { agentActions } from "./agentActions";
import { AgentCandidateCards } from "./AgentCandidateCards";
import { AgentChatStart } from "./AgentChatStart";
import { AgentConversationMenu } from "./AgentConversationMenu";
import { AgentHeader } from "./AgentHeader";
import { AgentOnboarding } from "./AgentOnboarding";
import { AgentPromptBar } from "./AgentPromptBar";
import { AgentRankingActivity } from "./AgentRankingActivity";
import { AgentThreadMessage } from "./AgentThreadMessage";
import { useRecruiterSession } from "./RecruiterLayout";
export function RecruitmentAgentPage() {
  const recruiter = useRecruiterSession();
  const [params, setParams] = useSearchParams();
  const [session, setSession] = useState<AgentSession | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [driveInbox, setDriveInbox] = useState<DriveWatchInbox | null>(null);
  const openChatRequested = params.get("start") === "chat";
  const [chatOpen, setChatOpen] = useState(openChatRequested);
  const selectedAction = agentActions.find((action) => action.id === params.get("action"));

  useEffect(() => {
    setSession(null);
    setCampaign(null);
    setDriveInbox(null);
    setEmails({});
    setChatOpen(openChatRequested);
  }, [recruiter.token, openChatRequested]);

  useEffect(() => {
    if (selectedAction) setMessage(selectedAction.prompt);
  }, [selectedAction]);

  useEffect(() => {
    const sessionId = params.get("session");
    if (!sessionId || !recruiter.token) return;
    let active = true;
    agentApi.getSession(sessionId, recruiter.token).then((restored) => {
      if (active) { setSession(restored); setCampaign(restored.campaign); }
    }).catch((cause: unknown) => {
      if (active) setError(
        cause instanceof Error ? cause.message : "Could not restore the agent session.");
    });
    return () => { active = false; };
  }, [params, recruiter.token]);

  useEffect(() => {
    if (!session || !recruiter.token || (session.setup_stage !== "ranking" && campaign?.status !== "approved" && session.messages.at(-1)?.role !== "user")) return;
    let active = true;
    const interval = window.setInterval(() => {
      agentApi.getSession(session.id, recruiter.token).then((restored) => {
        if (active) { setSession(restored); setCampaign(restored.campaign); }
      }).catch(() => undefined);
    }, 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, [session?.id, session?.setup_stage, campaign?.status, session?.messages.at(-1)?.role, recruiter.token]);

  useEffect(() => {
    if (!recruiter.token) return;
    let active = true;
    const refresh = () => agentApi.driveInbox(recruiter.token).then((inbox) => {
      if (active) setDriveInbox(inbox);
    }).catch(() => undefined);
    void refresh();
    const interval = window.setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 5000);
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { active = false; window.clearInterval(interval); document.removeEventListener("visibilitychange", onVisible); };
  }, [recruiter.token]);

  useEffect(() => {
    if (!campaign) return;
    setEmails((current) => Object.fromEntries(campaign.recipients.map((recipient) =>
      [recipient.candidate_id, current[recipient.candidate_id] ?? recipient.email ?? ""])));
  }, [campaign]);

  async function sendText(submitted: string) {
    if (!submitted.trim() || busy) return;
    const draft = submitted.trim();
    setMessage(""); setBusy(true); setError(null);
    let activeSession = session;
    try {
      if (!activeSession) {
        activeSession = await agentApi.createSession(undefined, recruiter.token, undefined, false);
        setSession(activeSession);
        setParams({ session: activeSession.id });
      }
      const response = await agentApi.send(activeSession.id, draft, recruiter.token);
      setSession(response.session); setCampaign(response.campaign);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Agent execution failed.");
      const restored = activeSession
        ? await agentApi.getSession(activeSession.id, recruiter.token).catch(() => null)
        : null;
      if (restored) {
        setSession(restored); setCampaign(restored.campaign);
      }
      const accepted = restored?.messages.slice(-2).some(
        (item) => item.role === "user" && item.content === draft,
      );
      if (!accepted) setMessage((current) => current || draft);
    }
    finally { setBusy(false); }
  }

  function send(event: FormEvent) { event.preventDefault(); void sendText(message); }

  function conversationDeleted(sessionId: string) { if (session?.id === sessionId) {
    setSession(null); setCampaign(null); setError(null); setChatOpen(true); setParams({});
  } }

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

  async function approveQuestions() {
    if (!session?.question_draft || !window.confirm("Approve these screening questions and prepare a campaign for recipient review? No email will be sent.")) return;
    setBusy(true); setError(null);
    try {
      const updated = await agentApi.approveQuestions(session.id, session.question_draft_revision, recruiter.token);
      setSession(updated); setCampaign(updated.campaign);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Question approval failed."); }
    finally { setBusy(false); }
  }

  async function saveContact(candidateId: string) {
    if (!session) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await batchApi.setContact(candidateId, emails[candidateId]?.trim() ?? "", recruiter.token);
      const restored = await agentApi.getSession(session.id, recruiter.token);
      setSession(restored); setCampaign(restored.campaign); setNotice("Candidate contact saved.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save contact."); }
    finally { setBusy(false); }
  }

  async function dispatch() {
    if (!session || !window.confirm("Send this campaign's invitations using the configured email provider?")) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await agentApi.dispatch(session.id, recruiter.token);
      setNotice("Email delivery started for this campaign.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start delivery."); }
    finally { setBusy(false); }
  }

  if (!session) return <main className="agent-page"><section className="agent-shell">
    <AgentHeader />
    {chatOpen
      ? <AgentChatStart busy={busy} error={error} message={message} setMessage={setMessage}
          send={send} token={recruiter.token}
          onOpen={(restored) => {
            setSession(restored); setCampaign(restored.campaign); setMessage(""); setParams({ session: restored.id });
          }}
          onNew={() => { setMessage(""); setError(null); }}
          onDeleted={conversationDeleted} onError={setError} />
      : <AgentOnboarding selectedActionLabel={selectedAction?.label} onOpenChat={() => setChatOpen(true)} />}
  </section></main>;

  return <main className="agent-page"><section className="agent-shell">
    <AgentHeader />
    <div className="agent-workspace">
      <section className="agent-chat">
        <AgentConversationMenu session={session} token={recruiter.token} onError={setError}
          onOpen={(restored) => { setSession(restored); setCampaign(restored.campaign); setMessage(""); setParams({ session: restored.id }); }}
          onNew={() => { setSession(null); setCampaign(null); setError(null); setChatOpen(true); setParams({}); }}
          onDeleted={conversationDeleted} />
        {error && <p className="agent-error" role="alert">{error}</p>}
        {notice && <p className="agent-notice" role="status">{notice}</p>}
        <div className="agent-thread">
          {session.messages.length === 0 && <article className="agent-message assistant"><span className="agent-avatar" aria-hidden="true">✦</span><div><strong>Recruitment Agent</strong><p>I’m connected to this job and its saved ranking run. What would you like me to do?</p></div></article>}
          {session.messages.map((item) => <AgentThreadMessage key={item.id} message={item} />)}
          {session.setup_stage === "ranked" && session.ranking_run_id && session.job_id &&
            <AgentCandidateCards jobId={session.job_id} runId={session.ranking_run_id} token={recruiter.token} />}
          {!busy && session.messages.at(-1)?.role === "user" && <p className="agent-notice" role="status">The last request has no completed response yet. Checking for an update.</p>}
          {busy && <article className="agent-message assistant agent-thinking"><span className="agent-avatar">✦</span><div><strong>Recruitment Agent</strong><p>Working through the recruitment tools…</p></div></article>}
          {!!driveInbox?.alerts.length && <section className="agent-drive-alert" role="status">
            <div className="agent-drive-alert-heading">
              <span className="agent-drive-alert-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><path d="M3 10h18"/></svg></span>
              <div><strong>Drive resumes to review</strong><p>{driveInbox.alerts.filter((item) => item.kind === "pdf").length} PDF · {driveInbox.alerts.filter((item) => item.kind === "docx").length} DOCX added or updated</p></div>
              <span className="agent-drive-alert-count">{driveInbox.alerts.length} to review</span>
            </div>
            <ul className="agent-drive-alert-files">{driveInbox.alerts.slice(0, 5).map((item) => <li key={item.id}><span className={`agent-drive-file-icon ${item.kind}`} aria-hidden="true">{item.kind.toUpperCase()}</span><span className="agent-drive-file-name">{item.name}</span><span className="agent-drive-file-type">{item.kind.toUpperCase()}</span></li>)}</ul>
            {driveInbox.alerts.length > 5 && <details className="agent-drive-alert-more">
              <summary>Show {driveInbox.alerts.length - 5} more files</summary>
              <ul className="agent-drive-alert-files">{driveInbox.alerts.slice(5).map((item) => <li key={item.id}><span className={`agent-drive-file-icon ${item.kind}`} aria-hidden="true">{item.kind.toUpperCase()}</span><span className="agent-drive-file-name">{item.name}</span><span className="agent-drive-file-type">{item.kind.toUpperCase()}</span></li>)}</ul>
            </details>}
            <div className="agent-drive-alert-footer"><a href={`/sources?source=drive&location=${encodeURIComponent(driveInbox.alerts[0].folder_url)}`}>Go to resume preview <span aria-hidden="true">→</span></a><span>Preview clears notices for that folder. Nothing is indexed until you confirm.</span></div>
          </section>}
          {session.question_draft && !session.question_config_id && <section className="agent-approval">
            <div className="agent-approval-title"><div><p className="agent-speaker">Approval checkpoint 1 of 2</p><strong>Screening questions</strong></div><span className="agent-status proposed">draft</span></div>
            <p className="agent-approval-summary">For the top {session.question_top_n} candidates · based on approved hiring criteria</p>
            <ol>{session.question_draft.must_haves.map((question) => <li key={question.id}>{qualificationQuestion(question.text)}</li>)}</ol>
            <p>Standard questions: {[
              session.question_draft.require_interest && "interest",
              session.question_draft.require_availability && "availability",
              session.question_draft.require_notice_period && "notice period",
              session.question_draft.require_salary && "salary",
            ].filter(Boolean).join(", ") || "none"}.</p>
            <p>Approving prepares a recipient review. It does not send email.</p>
            <button className="agent-approve-button" disabled={busy} onClick={approveQuestions}>Approve questions and review recipients</button>
          </section>}
          {campaign && <section className="agent-approval">
            <div className="agent-approval-title"><div><p className="agent-speaker">Approval checkpoint</p><strong>Screening campaign</strong></div><span className={`agent-status ${campaign.status}`}>{campaign.status}</span></div>
            <p className="agent-approval-summary">{campaign.proposed_candidate_ids.length} recipients <span>·</span> expires in {campaign.expiry_hours} hours</p>
            <div className="agent-recipient-list">{campaign.recipients.map((recipient) => <div key={recipient.candidate_id}><span>{recipient.display_name ?? recipient.candidate_id}</span>
              {recipient.email ? <small>{recipient.email}</small> : <div className="agent-contact-input"><input type="email" aria-label={`Email for ${recipient.candidate_id}`} value={emails[recipient.candidate_id] ?? ""} onChange={(event) => setEmails({...emails, [recipient.candidate_id]: event.target.value})} placeholder="Candidate email" /><button type="button" disabled={busy || !emails[recipient.candidate_id]?.trim()} onClick={() => saveContact(recipient.candidate_id)}>Save</button></div>}
            </div>)}</div>
            {campaign.questions?.must_haves.length ? <details><summary>{campaign.questions.must_haves.length} screening questions</summary><ol>{campaign.questions.must_haves.map((question) => <li key={question.id}>{qualificationQuestion(question.text)}</li>)}</ol></details> : null}
            <div className="agent-approval-meta"><p><span>Invitation</span>{campaign.message_template}</p><p><span>Sender</span>{campaign.sender.email ?? campaign.sender.backend}</p></div>
            {campaign.status === "proposed" && <button className="agent-approve-button" disabled={busy || campaign.recipients.some((recipient) => !recipient.email)} onClick={approve}>Approve and queue invitations</button>}
            {campaign.status === "approved" && <div className="agent-delivery" role="status"><p>
              {campaign.delivery.counts.unknown
                ? "Delivery could not be confirmed · check authorization before retrying"
                : campaign.delivery.counts.sent
                  ? "Approved · provider accepted delivery"
                  : "Approved · invitations queued"}
            </p>{Object.entries(campaign.delivery.counts).map(([status, count]) => <span key={status}>{status} {count}</span>)}
              {Object.keys(campaign.delivery.counts).some((status) => status === "pending" || status === "failed") && <button type="button" disabled={busy} onClick={dispatch}>Send invitations</button>}
            </div>}
          </section>}
        </div>
        <AgentRankingActivity session={session} />
        <AgentPromptBar session={session} busy={busy} onSend={(prompt) => void sendText(prompt)} onDraft={setMessage} />
        <form onSubmit={send} className="agent-composer"><textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Paste a JD or ask about candidates…" rows={3} maxLength={18000} disabled={busy} aria-label="Message Recruitment Agent" onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
        }} /><button aria-label="Send message" disabled={busy || !message.trim()}>↑</button></form>
      </section>
    </div>
  </section></main>;
}
