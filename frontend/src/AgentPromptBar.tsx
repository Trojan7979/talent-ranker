import { useEffect, useRef } from "react";
import type { AgentSession } from "./agentApi";
import { agentPrompts } from "./agentPrompts";

type Props = { session: AgentSession; busy: boolean; onSend: (prompt: string) => void; onDraft: (prompt: string) => void };

export function AgentPromptBar({ session, busy, onSend, onDraft }: Props) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOnOutside = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) menu.current?.removeAttribute("open");
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") menu.current?.removeAttribute("open");
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  const prompts = agentPrompts.forSession(session);
  const choose = (prompt: string) => prompt === "I approve this JD" ? onSend(prompt) : onDraft(prompt);
  return <div className="agent-prompt-bar" aria-label="Suggested prompts">
    {prompts.slice(0, 2).map((item) =>
      <button type="button" key={item.label} disabled={busy} onClick={() => choose(item.prompt)}>{item.label}</button>)}
    <details className="agent-prompt-menu" ref={menu}><summary>More prompts</summary>
      <div className="agent-prompt-list">{prompts.slice(2).map((item) =>
        <button type="button" key={item.label} disabled={busy} onClick={() => {
          choose(item.prompt); menu.current?.removeAttribute("open");
        }}>{item.label}: {item.prompt}</button>)}</div>
    </details>
  </div>;
}
