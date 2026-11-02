import type { Campaign } from "./screeningApi";

export type SelectionRule = {
  kind: "top_n" | "rank_cutoff" | "score_threshold";
  value: number;
};

export type JobConfig = {
  id: string;
  job_profile_version_id: string;
  version: number;
  questions: { must_haves: { id: string; text: string; hard_fail_on_no: boolean }[] };
};
export type QuestionDraft = {
  version: number;
  must_haves: { id: string; text: string; hard_fail_on_no: boolean }[];
  require_interest: boolean;
  require_availability: boolean;
  require_notice_period: boolean;
  require_salary: boolean;
  max_notice_days: number | null;
  target_start_date: string | null;
  salary_maximum: number | null;
  salary_currency: string | null;
  salary_period: "hour" | "month" | "year" | null;
};

export type ContactPreview = { candidate_id: string; display_name: string | null; name_source: string | null;
  email: string | null; contactable: boolean };
export type SelectionPreview = {
  matching_count: number;
  candidates: { candidate_id: string; rank: number; score: number; has_contact: boolean }[];
};

const base = "/api/screening";
async function request<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  void token;
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json();
}

export const batchApi = {
  questionDraft: (jobId: string, profileId: string, token: string) =>
    request<QuestionDraft>(
      `/jobs/${encodeURIComponent(jobId)}/profiles/${encodeURIComponent(profileId)}/question-draft`,
      token,
    ),
  configVersion: (jobId: string, version: number, token: string) =>
    request<JobConfig>(`/jobs/${encodeURIComponent(jobId)}/configs/${version}`, token),
  latestConfig: async (jobId: string, token: string): Promise<JobConfig | null> => {
    void token;
    const response = await fetch(`${base}/jobs/${encodeURIComponent(jobId)}/latest-config`);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Question configuration: HTTP ${response.status}`);
    return response.json();
  },
  createConfig: (jobId: string, profileId: string, version: number, questions: object, token: string) =>
    request<JobConfig>(`/jobs/${encodeURIComponent(jobId)}/configs`, token, {
      method: "POST", body: JSON.stringify({ job_profile_version_id: profileId, questions: { ...questions, version } }),
    }),
  contacts: (candidateIds: string[], token: string) =>
    request<ContactPreview[]>("/contacts/lookup", token, {
      method: "POST", body: JSON.stringify({ candidate_ids: candidateIds }),
    }),
  setName: (candidateId: string, displayName: string, token: string) =>
    request<{ candidate_id: string; display_name: string }>(
      `/candidates/${encodeURIComponent(candidateId)}/name`, token, {
        method: "PUT", body: JSON.stringify({ display_name: displayName }),
      }),
  setContact: (candidateId: string, email: string, token: string) =>
    request<ContactPreview>(`/candidates/${encodeURIComponent(candidateId)}/contact`, token, {
      method: "PUT", body: JSON.stringify({ email, source: "recruiter-frontend", contactable: true }),
    }),
  preview: (jobId: string, runId: string, rule: SelectionRule, token: string) =>
    request<SelectionPreview>("/selections", token, {
      method: "POST", body: JSON.stringify({ job_id: jobId, ranking_run_id: runId, rule }),
    }),
  propose: (jobId: string, runId: string, configId: string, rule: SelectionRule,
    messageTemplate: string, expiryHours: number, token: string) =>
    request<Campaign>("/campaigns", token, {
      method: "POST", body: JSON.stringify({ job_id: jobId, ranking_run_id: runId, config_id: configId,
        rule, message_template: messageTemplate, expiry_hours: expiryHours }),
    }),
  edit: (campaignId: string, revision: number, finalIds: string[], messageTemplate: string, token: string) =>
    request<Campaign>(`/campaigns/${campaignId}`, token, {
      method: "PATCH", body: JSON.stringify({ expected_revision: revision,
        final_candidate_ids: finalIds, message_template: messageTemplate }),
    }),
};
