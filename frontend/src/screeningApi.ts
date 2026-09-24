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
  getCampaign: (id: string, token: string) =>
    request<Campaign>(`/campaigns/${id}`, { headers: recruiter(token) }),
  approveCampaign: (id: string, revision: number, token: string) =>
    request<Campaign>(`/campaigns/${id}/approve`, {
      method: "POST", headers: recruiter(token), body: JSON.stringify({ expected_revision: revision }),
    }),
  getResults: (id: string, token: string) =>
    request<ReviewPage>(`/campaigns/${id}/results`, { headers: recruiter(token) }),
  getInvite: (token: string) => request<Invite>(`/invites/${encodeURIComponent(token)}`),
  event: (token: string, event: "opened" | "started" | "decline") =>
    request<Invite>(`/invites/${encodeURIComponent(token)}/${event}`, { method: "POST" }),
  complete: (token: string, answers: Answers) =>
    request<{ outcome: string }>(`/invites/${encodeURIComponent(token)}/complete`, {
      method: "POST", body: JSON.stringify({ expected_revision: 0, answers }),
    }),
};
