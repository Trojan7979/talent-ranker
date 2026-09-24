import { ChangeEvent, FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  approveJobProfile,
  calibrateJob,
  rankCandidates,
  updateJobProfile,
} from "./api";
import type { JobProfile } from "./api";
import { CalibrationPanel } from "./CalibrationPanel";

export function RankingPage() {
  const navigate = useNavigate();
  const [jobId, setJobId] = useState("senior-ai-engineer");
  const [jobDescription, setJobDescription] = useState("");
  const [topK, setTopK] = useState(2);
  const [profile, setProfile] = useState<JobProfile | null>(null);
  const [approvedBy, setApprovedBy] = useState("recruiter");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function loadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    setError(null);
    try {
      const parts = await Promise.all(
        files.map(async (file) => {
          const content = (await file.text()).trim();
          return files.length > 1 ? `JD part: ${file.name}\n${content}` : content;
        }),
      );
      setJobDescription(parts.join("\n\n"));
      setProfile(null);
    } catch {
      setError("Could not read the selected JD file.");
    }
  }

  async function calibrate(event: FormEvent) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      setProfile(await calibrateJob(jobId, jobDescription));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Calibration failed");
    } finally {
      setIsLoading(false);
    }
  }

  async function approveAndRank() {
    if (!profile) return;
    setIsLoading(true);
    setError(null);
    try {
      let approved = profile;
      if (profile.status === "draft") {
        const updated = await updateJobProfile(profile);
        approved = await approveJobProfile(updated.profile_version_id, approvedBy);
      }
      setProfile(approved);
      const response = await rankCandidates(jobId, approved.profile_version_id, topK);
      navigate(`/jobs/${encodeURIComponent(jobId)}/ranking-runs/${response.run_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval or ranking failed");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="workspace">
      <section className="query-panel">
        <h1>Talent Ranker</h1>
        <form onSubmit={calibrate}>
          <label>
            Job ID
            <input value={jobId} onChange={(event) => setJobId(event.target.value)} />
          </label>
          <label>
            Number of candidates
            <input
              type="number"
              min={1}
              max={1000}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value))}
            />
          </label>
          <label>
            Load JD files
            <input type="file" accept=".txt,.md" multiple onChange={loadFiles} />
            <span className="hint">Select one or more TXT/Markdown parts.</span>
          </label>
          <label>
            Job description preview
            <textarea
              value={jobDescription}
              onChange={(event) => {
                setJobDescription(event.target.value);
                setProfile(null);
              }}
              rows={12}
            />
          </label>
          <button disabled={isLoading || jobDescription.length < 20}>
            {isLoading ? "Working..." : "Calibrate hiring criteria"}
          </button>
        </form>
        {profile && (
          <CalibrationPanel
            profile={profile}
            approvedBy={approvedBy}
            busy={isLoading}
            onChange={setProfile}
            onApprovedByChange={setApprovedBy}
            onApproveAndRank={approveAndRank}
          />
        )}
        {error && <p className="error">{error}</p>}
      </section>
      <section className="results-panel" aria-label="Ranking workspace">
        <p className="hint">Approve hiring criteria and run ranking to open a saved shortlist.</p>
      </section>
    </main>
  );
}
