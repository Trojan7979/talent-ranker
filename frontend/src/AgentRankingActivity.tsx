import type { AgentSession } from "./agentApi";

export function AgentRankingActivity({ session }: { session: AgentSession }) {
  if (session.setup_stage !== "ranking") return null;
  const events = session.ranking_events?.length
    ? session.ranking_events
    : [session.ranking_progress || "Ranking request queued; waiting for the worker"];
  const steps = session.ranking_status === "failed"
    ? [...events, "Ranking stopped. Use Retry ranking after checking the worker."]
    : events;
  return <section className="agent-ranking-activity" aria-label="Ranking activity">
    <strong>Ranking activity</strong>
    <ol>{steps.map((step, index) => <li key={`${index}-${step}`}
      role={index === steps.length - 1 ? "status" : undefined}>{step}</li>)}</ol>
  </section>;
}
