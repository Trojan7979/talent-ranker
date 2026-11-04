import type { FormEvent } from "react";
import type { AgentSession } from "./agentApi";
import { AgentConversationMenu } from "./AgentConversationMenu";
import { CopyTextButton } from "./CopyTextButton";

const INTRO = "Tell me about the role or paste the job description. I’ll extract the hiring criteria for your review before ranking.";

type Props = {
  busy: boolean;
  error: string | null;
  message: string;
  setMessage: (value: string) => void;
  send: (event: FormEvent) => void;
  token: string;
  onOpen: (session: AgentSession) => void;
  onNew: () => void;
  onDeleted: (sessionId: string) => void;
  onError: (message: string | null) => void;
};

export function AgentChatStart({
  busy, error, message, setMessage, send, token, onOpen, onNew, onDeleted, onError,
}: Props) {
  return <div className="agent-workspace"><section className="agent-chat">
    <AgentConversationMenu session={null} token={token} onOpen={onOpen} onNew={onNew}
      onDeleted={onDeleted} onError={onError} />
    {error && <p className="agent-error" role="alert">{error}</p>}
    <div className="agent-thread">
      <article className="agent-message assistant"><span className="agent-avatar" aria-hidden="true">✦</span><div>
        <strong>Recruitment Agent</strong><p>{INTRO}</p><CopyTextButton text={INTRO} />
      </div></article>
      {busy && <article className="agent-message assistant agent-thinking"><span className="agent-avatar">✦</span><div><strong>Recruitment Agent</strong><p>Starting your conversation…</p></div></article>}
    </div>
    <form onSubmit={send} className="agent-composer"><textarea value={message}
      onChange={(event) => setMessage(event.target.value)}
      placeholder="Paste a JD or describe the role…" rows={3} maxLength={18000}
      disabled={busy} aria-label="Message Recruitment Agent" onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault(); event.currentTarget.form?.requestSubmit();
        }
      }} /><button aria-label="Send message" disabled={busy || !message.trim()}>↑</button></form>
  </section></div>;
}
