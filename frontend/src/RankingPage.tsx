import { useNavigate } from "react-router-dom";
import { RankingSetup } from "./RankingSetup";

export function RankingPage() {
  const navigate = useNavigate();
  return <main className="workspace">
    <section className="query-panel">
      <h1>Talent Ranker</h1>
      <RankingSetup onRanked={(jobId, runId) => navigate(`/jobs/${encodeURIComponent(jobId)}/ranking-runs/${runId}`)} />
    </section>
    <section className="results-panel" aria-label="Ranking workspace">
      <p className="hint">Approve hiring criteria and run ranking to open a saved shortlist.</p>
    </section>
  </main>;
}
