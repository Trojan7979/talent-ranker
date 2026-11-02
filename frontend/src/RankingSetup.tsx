import { ChangeEvent, FormEvent, useState } from "react";
import { approveJobProfile, calibrateJob, rankCandidates, updateJobProfile } from "./api";
import type { JobProfile } from "./api";
import { CalibrationPanel } from "./CalibrationPanel";
import { RecruiterTokenField } from "./RecruiterTokenField";

type Props = {
  initialJobId?: string;
  onRanked: (jobId: string, runId: string) => void | Promise<void>;
};

export function RankingSetup({ initialJobId = "senior-ai-engineer", onRanked }: Props) {
  const [jobId, setJobId] = useState(initialJobId);
  const [jobDescription, setJobDescription] = useState("");
  const [topK, setTopK] = useState(2);
  const [profile, setProfile] = useState<JobProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedRunId, setSavedRunId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  function changeJobId(value: string) {
    setJobId(value);
    setProfile(null);
    setSavedRunId(null);
  }

  async function loadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    setError(null);
    try {
      const parts = await Promise.all(files.map(async (file) => {
        const content = (await file.text()).trim();
        return files.length > 1 ? `JD part: ${file.name}\n${content}` : content;
      }));
      setJobDescription(parts.join("\n\n"));
      setProfile(null);
      setSavedRunId(null);
    } catch {
      setError("Could not read the selected JD file.");
    }
  }

  async function calibrate(event: FormEvent) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    setSavedRunId(null);
    try {
      setProfile(await calibrateJob(jobId.trim(), jobDescription));
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
        approved = await approveJobProfile(updated.profile_version_id);
      }
      setProfile(approved);
      const response = await rankCandidates(jobId.trim(), approved.profile_version_id, topK);
      setSavedRunId(response.run_id);
      await onRanked(jobId.trim(), response.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval or ranking failed");
    } finally {
      setIsLoading(false);
    }
  }

  return <div className="ranking-setup">
    <form onSubmit={calibrate}>
      <RecruiterTokenField />
      <label>Job ID<input required value={jobId} onChange={(event) => changeJobId(event.target.value)} /></label>
      <label>Number of candidates
        <input type="number" min={1} max={1000} value={topK}
          onChange={(event) => setTopK(Number(event.target.value))} />
        <span className="hint">How many candidates to include in the saved shortlist.</span>
      </label>
      <label>Load JD files<input type="file" accept=".txt,.md" multiple onChange={loadFiles} />
        <span className="hint">Select one or more TXT/Markdown parts.</span>
      </label>
      <label>Job description preview
        <textarea value={jobDescription} onChange={(event) => {
          setJobDescription(event.target.value);
          setProfile(null);
          setSavedRunId(null);
        }} rows={10} />
      </label>
      <button disabled={isLoading || !jobId.trim() || jobDescription.trim().length < 20 || !Number.isInteger(topK) || topK < 1 || topK > 1000}>
        {isLoading ? "Working..." : "Calibrate hiring criteria"}
      </button>
    </form>
    {profile && <CalibrationPanel profile={profile} busy={isLoading}
      onChange={setProfile} onApproveAndRank={approveAndRank} />}
    {savedRunId && <p className="hint">Saved shortlist: <a href={`/jobs/${encodeURIComponent(jobId.trim())}/ranking-runs/${savedRunId}`}>View run</a></p>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
