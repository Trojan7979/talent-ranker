import { useState } from "react";
import { agentApi } from "./agentApi";
import type { AgentSession, AgentSessionSummary } from "./agentApi";

type Props = {
  session: AgentSession | null;
  token: string;
  onOpen: (session: AgentSession) => void;
  onNew: () => void;
  onDeleted: (sessionId: string) => void;
  onError: (message: string | null) => void;
};

export function AgentConversationMenu({ session, token, onOpen, onNew, onDeleted, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AgentSessionSummary[]>([]);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (open) { setOpen(false); return; }
    setOpen(true); setBusy(true); onError(null);
    try { setItems(await agentApi.listSessions(token)); }
    catch (cause) { onError(cause instanceof Error ? cause.message : "Could not load conversations."); }
    finally { setBusy(false); }
  }

  async function select(id: string) {
    if (id === session?.id) { setOpen(false); return; }
    setBusy(true); onError(null);
    try { onOpen(await agentApi.getSession(id, token)); setOpen(false); }
    catch (cause) { onError(cause instanceof Error ? cause.message : "Could not open conversation."); }
    finally { setBusy(false); }
  }

  async function remove(item: AgentSessionSummary) {
    if (!window.confirm("Delete this conversation and its messages?")) return;
    setBusy(true); onError(null);
    try {
      await agentApi.deleteSession(item.id, token);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
      onDeleted(item.id);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Could not delete conversation.");
    } finally { setBusy(false); }
  }

  return <div className="agent-context">
    <span>{session?.job_id ?? "New conversation"}</span>
    <small>{session?.ranking_run_id ? `Run ${session.ranking_run_id}` : "Signed-in recruiter workspace"}</small>
    <button type="button" aria-expanded={open} aria-controls="agent-conversation-menu" onClick={() => void toggle()}>Your conversations</button>
    {open && <div id="agent-conversation-menu" className="agent-conversation-menu" aria-label="Your conversations">
      <strong>Recent conversations</strong>
      {busy && <p>Loading…</p>}
      {!busy && items.length === 0 && <p>No conversations found.</p>}
      <ul>{items.map((item) => <li key={item.id} className="agent-conversation-row">
        <button type="button" disabled={busy} aria-current={item.id === session?.id ? "page" : undefined} onClick={() => void select(item.id)}>
          <span>{item.job_id ?? "New role"}{item.id === session?.id ? " · Current" : ""}</span><small>{new Date(item.updated_at).toLocaleString()} · {item.setup_stage === "ranked" ? "Ranking saved" : "In progress"}</small>
        </button>
        <button type="button" className="agent-conversation-delete" disabled={busy}
          aria-label={`Delete conversation ${item.job_id ?? item.id}`}
          onClick={() => void remove(item)}>Delete</button>
      </li>)}</ul>
      <button type="button" className="agent-new-conversation" onClick={onNew}>Start a new conversation</button>
    </div>}
  </div>;
}
