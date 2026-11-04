import { useState } from "react";

type Props = { text: string; label?: string };

export function CopyTextButton({ text, label = "Copy message" }: Props) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("failed");
    }
    window.setTimeout(() => setStatus("idle"), 1600);
  }

  return <button type="button" className="agent-message-copy" onClick={() => void copy()}
    aria-label={status === "copied" ? "Copied" : status === "failed" ? "Copy failed" : label}
    title={status === "copied" ? "Copied" : status === "failed" ? "Copy failed" : label}>
    {status === "copied"
      ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
      : <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="10" height="10" rx="2" /><path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" /></svg>}
  </button>;
}
