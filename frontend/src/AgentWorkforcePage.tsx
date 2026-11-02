import { Link } from "react-router-dom";
import { agentActions } from "./agentActions";

export function AgentWorkforcePage() {
  return <main className="workforce-page">
    <header className="workforce-header">
      <div><p className="workforce-eyebrow">Agent Workforce</p><h1>Your autonomous workforce</h1>
        <p>Open a specialized agent workspace to start, monitor, and approve work.</p></div>
      <span className="workforce-count">1 agent available</span>
    </header>

    <section className="workforce-grid" aria-label="Available agents">
      <article className="workforce-card">
        <div className="workforce-card-top">
          <span className="workforce-agent-icon" aria-hidden="true">✦</span>
          <span className="workforce-status"><i />Available</span>
        </div>
        <div className="workforce-card-copy">
          <p className="workforce-kind">Talent acquisition</p>
          <h2>Recruitment Agent</h2>
          <p>Guides role setup in chat, explains saved rankings, prepares screening drafts, and reports campaign progress. Recruiters approve criteria and outreach.</p>
        </div>
        <div className="workforce-actions" aria-label="Recruitment Agent actions">
          {agentActions.map((action) => <Link key={action.id} to={`/agents/recruitment?action=${action.id}`}>
            <strong>{action.label}</strong><span>{action.description}</span>
          </Link>)}
        </div>
        <Link className="workforce-open" to="/agents/recruitment">Open workspace <span aria-hidden="true">→</span></Link>
      </article>

      <article className="workforce-card workforce-card-placeholder" aria-label="Future agent">
        <span className="workforce-plus" aria-hidden="true">+</span><h2>More agents coming</h2>
        <p>Additional specialized agents will appear here as they are deployed.</p>
      </article>
    </section>
  </main>;
}
