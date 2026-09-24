export type CandidateScore = {
  candidate_id: string;
  rank: number;
  score: number;
  score_components: Record<string, number>;
  evidence: string[];
  reasoning: string;
};

export type RankResponse = {
  run_id: string;
  results: CandidateScore[];
};

export type HiringPriorities = {
  must_have_skills: string[];
  preferred_skills: string[];
  must_have_requirements: string[];
  preferred_requirements: string[];
  minimum_years_experience: number | null;
  seniority: string | null;
  location: {
    locations: string[];
    remote_policy: "onsite" | "hybrid" | "remote" | null;
  };
  availability: {
    max_notice_period_days: number | null;
    target_start_date: string | null;
  };
  compensation: {
    currency: string | null;
    minimum: number | null;
    maximum: number | null;
    period: "hour" | "month" | "year" | null;
  };
};

export type JobProfile = {
  profile_version_id: string;
  job_id: string;
  version: number;
  status: "draft" | "approved" | "superseded";
  job_description: string;
  priorities: HiringPriorities;
  approved_by: string | null;
  calibration_metadata?: {
    method?: "rules" | "llm";
    model?: string;
    prompt_version?: string;
  };
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function parseResponse<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail ?? `${action} failed with HTTP ${response.status}`);
  }
  return response.json();
}

export async function calibrateJob(jobId: string, jobDescription: string): Promise<JobProfile> {
  const response = await fetch(`${apiBaseUrl}/jobs/calibrate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, job_description: jobDescription }),
  });
  return parseResponse(response, "Calibration");
}

export async function updateJobProfile(profile: JobProfile): Promise<JobProfile> {
  const response = await fetch(`${apiBaseUrl}/job-profiles/${profile.profile_version_id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ priorities: profile.priorities }),
  });
  return parseResponse(response, "Profile update");
}

export async function approveJobProfile(
  profileVersionId: string,
  approvedBy: string,
): Promise<JobProfile> {
  const response = await fetch(`${apiBaseUrl}/job-profiles/${profileVersionId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved_by: approvedBy }),
  });
  return parseResponse(response, "Profile approval");
}

export async function rankCandidates(
  jobId: string,
  profileVersionId: string,
  topK = 20,
): Promise<RankResponse> {
  const response = await fetch(`${apiBaseUrl}/rank`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: jobId,
      job_profile_version_id: profileVersionId,
      top_k: topK,
    }),
  });
  return parseResponse(response, "Ranking request");
}
