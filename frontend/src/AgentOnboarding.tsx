import { Link } from "react-router-dom";
import "./agentOnboarding.css";

type Props = {
  selectedActionLabel?: string;
  onOpenChat: () => void;
};

export function AgentOnboarding({ selectedActionLabel, onOpenChat }: Props) {
  return <div className="agent-onboarding">
    <div className="agent-welcome">
      <p className="agent-speaker">Recruitment Agent</p>
      <h2>What would you like to accomplish?</h2>
      <p>Start with your resumes, then tell me about the role. I will guide you through criteria, ranking, evidence, and screening in chat.</p>
      <ol className="agent-start-steps">
        <li><strong>Connect resumes</strong><span>Choose a configured Drive or SharePoint folder, review candidate matches, and approve indexing.</span><Link to="/sources">Open resume sources</Link></li>
        <li><strong>Describe the role</strong><span>Open chat and paste a job description or provide the responsibilities and requirements.</span></li>
        <li><strong>Review and rank</strong><span>Approve the extracted criteria before ranking. Screening and outreach require separate approval.</span></li>
      </ol>
      {selectedActionLabel && <p className="agent-selected-action">Selected: {selectedActionLabel}. Open chat to continue.</p>}
    </div>
    <div className="agent-connect-card">
      <div><strong>Recruitment workspace</strong><p>Start a new conversation or return to a completed shortlist.</p></div>
      <div className="agent-connect-actions">
        <button type="button" onClick={onOpenChat}>Open chat</button>
        <Link to="/shortlists">View saved shortlists</Link>
      </div>
      <p className="hint">The agent will ask for the job description and show hiring criteria for approval.</p>
    </div>
  </div>;
}
