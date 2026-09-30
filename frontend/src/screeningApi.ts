export type Campaign = {
  id: string;
  job_id: string;
  ranking_run_id: string;
  job_profile_version_id: string;
  proposed_candidate_ids: string[];
  final_candidate_ids: string[] | null;
  message_template: string;
  expiry_hours: number;
  status: "proposed" | "approved" | "rejected";
  revision: number;
  approved_by: string | null;
};

export type CompletedScreening = {
  id: string;
  candidate_id: string;
  config_version: number;
  outcome: "proceed_to_interview" | "needs_recruiter_review" | "do_not_proceed";
  confirmed: string[];
  missing: string[];
  needs_verification: string[];
  completed_at: string;
};

export type ReviewPage = {
  items: CompletedScreening[];
  counts: Record<CompletedScreening["outcome"], number>;
  next_cursor: string | null;
};

export type ActivityPage = {
  campaign_id: string;
  items: {
    invite_id: string;
    candidate_id: string;
    recipient_email: string;
    delivery_status: "pending" | "processing" | "sent" | "failed" | "cancelled";
    status: Invite["status"];
    sent_at: string | null;
    opened_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    expires_at: string;
  }[];
  next_cursor: string | null;
};

export type Invite = {
  id: string;
  campaign_id: string;
  job_id: string;
  status: "sent" | "opened" | "started" | "completed" | "expired" | "declined" | null;
  expires_at: string;
  questions: {
    must_haves: { id: string; text: string }[];
    require_interest: boolean;
    require_availability: boolean;
    require_notice_period: boolean;
    require_salary: boolean;
  };
};

export type Answers = {
  qualifications: { requirement_id: string; confirmation: "yes" | "no" | "unsure" }[];
  interest?: "interested" | "not_interested" | "needs_details" | "unsure";
  availability?: { status: "answered" | "unsure" | "prefer_not_to_answer"; earliest_start_date?: string };
  notice_period?: { status: "answered" | "unsure" | "prefer_not_to_answer"; days?: number };
  salary?: {
    status: "answered" | "unsure" | "prefer_not_to_answer";
    minimum?: number;
    maximum?: number;
    currency?: string;
    period?: "hour" | "month" | "year";
    negotiable?: boolean;
  };
};

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/screening${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json();
}

function recruiter(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export const screeningApi = {
  gmailStatus: (token: string) => request<{
    backend: string; sender_email: string | null; connected: boolean;
  }>("/sender/gmail/status", { headers: recruiter(token) }),
  connectGmail: (campaignId: string, token: string) =>
    request<{ authorization_url: string }>("/sender/gmail/connect", {
      method: "POST", headers: recruiter(token), body: JSON.stringify({ campaign_id: campaignId }),
    }),
  getCampaign: (id: string, token: string) =>
    request<Campaign>(`/campaigns/${id}`, { headers: recruiter(token) }),
  approveCampaign: (id: string, revision: number, token: string) =>
    request<Campaign>(`/campaigns/${id}/approve`, {
      method: "POST", headers: recruiter(token), body: JSON.stringify({ expected_revision: revision }),
    }),
  dispatchCampaign: (id: string, token: string) =>
    request<{ campaign_id: string; status: "scheduled" }>(`/campaigns/${id}/dispatch`, {
      method: "POST", headers: recruiter(token),
    }),
  getResults: (id: string, token: string) =>
    request<ReviewPage>(`/campaigns/${id}/results`, { headers: recruiter(token) }),
  getActivity: (id: string, token: string) =>
    request<ActivityPage>(`/campaigns/${id}/invites?limit=200`, { headers: recruiter(token) }),
  exportResults: async (id: string, candidateIds: string[], token: string): Promise<Blob> => {
    const response = await fetch(`/api/screening/campaigns/${id}/exports`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...recruiter(token) },
      body: JSON.stringify({ candidate_ids: candidateIds }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(typeof body?.detail === "string" ? body.detail : `Export failed: HTTP ${response.status}`);
    }
    return response.blob();
  },
  getInvite: (token: string) => request<Invite>(`/invites/${encodeURIComponent(token)}`),
  event: (token: string, event: "opened" | "started" | "decline") =>
    request<Invite>(`/invites/${encodeURIComponent(token)}/${event}`, { method: "POST" }),
  complete: (token: string, answers: Answers) =>
    request<{ outcome: string }>(`/invites/${encodeURIComponent(token)}/complete`, {
      method: "POST", body: JSON.stringify({ expected_revision: 0, answers }),
    }),
};
