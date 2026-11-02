import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { RankingPage } from "./RankingPage";
import { ShortlistPage } from "./ShortlistPage";
import { CampaignPage } from "./CampaignPage";
import { CandidatePage } from "./CandidatePage";
import { RecruiterLayout } from "./RecruiterLayout";
import { AgentWorkforcePage } from "./AgentWorkforcePage";
import { RecruitmentAgentPage } from "./RecruitmentAgentPage";
import { SavedRunsPage } from "./SavedRunsPage";
import { CampaignsPage } from "./CampaignsPage";
import { ResumeSourcesPage } from "./ResumeSourcesPage";
import "./agentWorkspace.css";
import "./styles.css";
import "./resumeSources.css";

function SavedRunRoute() {
  const { jobId, runId } = useParams();
  return <ShortlistPage key={`${jobId}/${runId}`} />;
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <BrowserRouter>
    <Routes>
      <Route element={<RecruiterLayout />}>
        <Route path="/" element={<Navigate to="/ranking" replace />} />
        <Route path="/ranking" element={<RankingPage />} />
        <Route path="/sources" element={<ResumeSourcesPage />} />
        <Route path="/shortlists" element={<SavedRunsPage />} />
        <Route path="/screening/campaigns" element={<CampaignsPage />} />
        <Route path="/agents" element={<AgentWorkforcePage />} />
        <Route path="/agents/recruitment" element={<RecruitmentAgentPage />} />
        <Route path="/jobs/:jobId/ranking-runs/:runId" element={<SavedRunRoute />} />
        <Route path="/screening/campaigns/:campaignId" element={<CampaignPage />} />
      </Route>
      <Route path="/s/:token" element={<CandidatePage />} />
    </Routes>
  </BrowserRouter>,
);
