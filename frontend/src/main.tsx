import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { RankingPage } from "./RankingPage";
import { ShortlistPage } from "./ShortlistPage";
import { CampaignPage } from "./CampaignPage";
import { CandidatePage } from "./CandidatePage";
import "./styles.css";

function SavedRunRoute() {
  const { jobId, runId } = useParams();
  return <ShortlistPage key={`${jobId}/${runId}`} />;
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<Navigate to="/ranking" replace />} />
      <Route path="/ranking" element={<RankingPage />} />
      <Route path="/jobs/:jobId/ranking-runs/:runId" element={<SavedRunRoute />} />
      <Route path="/screening/campaigns/:campaignId" element={<CampaignPage />} />
      <Route path="/s/:token" element={<CandidatePage />} />
    </Routes>
  </BrowserRouter>,
);
