import type { AgentMessage } from "./agentApi";
import { CopyTextButton } from "./CopyTextButton";

type Props = { message: AgentMessage };

export function AgentThreadMessage({ message }: Props) {
  const content = message.role === "assistant" && message.content.startsWith("Ranking finished. I saved ")
    ? `${message.content.split("\n")[0]}\nReview the candidate cards below for names, scores, and evidence.`
    : message.content;
  return <article className={`agent-message ${message.role}`}>
    {message.role === "assistant" && <span className="agent-avatar" aria-hidden="true">✦</span>}
    <div><strong>{message.role === "user" ? "Recruiter" : "Recruitment Agent"}</strong>
      <p>{content}</p><CopyTextButton text={message.content} />
    </div>
  </article>;
}
