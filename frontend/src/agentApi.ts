export type AgentMessage = { id: number; role: "user" | "assistant"; content: string; created_at: string };
export type AgentSessionSummary = { id: string; job_id: string | null; setup_stage: AgentSession["setup_stage"];
  ranking_run_id: string | null; created_at: string; updated_at: string };
export type DriveWatchSchedule = "instant" | "daily" | "weekends";
export type DriveWatchInbox = {
  watches: { id: string; folder_url: string; last_scan_at: string | null; last_error: string | null;
    notification_schedule: DriveWatchSchedule; notification_timezone: string; next_scan_at: string }[];
  alerts: { id: number; file_id: string; name: string; kind: "pdf" | "docx"; created_at: string; folder_url: string }[];
};
export type AgentSession = {
  id: string; job_id: string | null; ranking_run_id: string | null; campaign_id: string | null;
  setup_stage: "awaiting_jd" | "awaiting_jd_approval" | "awaiting_criteria_approval" | "ranking" | "ranked";
  ranking_status: "pending" | "running" | "completed" | "failed" | null;
  question_draft: { must_haves: { id: string; text: string }[]; require_interest: boolean;
    require_availability: boolean; require_notice_period: boolean; require_salary: boolean } | null;
  question_top_n: number | null; question_draft_revision: number; question_config_id: string | null;
  created_at: string; messages: AgentMessage[]; campaign: Campaign | null;
};
export type Campaign = {
  id: string; job_id: string; proposed_candidate_ids: string[]; final_candidate_ids: string[] | null;
  message_template: string; expiry_hours: number; status: "proposed" | "approved" | "rejected";
  revision: number;
  recipients: { candidate_id: string; display_name: string | null; email: string | null; contactable: boolean }[];
  questions: { must_haves: { id: string; text: string }[] } | null;
  sender: { backend: string; email: string | null };
  delivery: {
    counts: Record<string, number>;
    items: { candidate_id: string; recipient_email: string; delivery_status: string; status: string }[];
  };
};

async function request<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/agent${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const agentApi = {
  availableJobs: (token: string) => request<{ job_ids: string[] }>("/jobs", token),
  watchDrive: (folderUrl: string, schedule: DriveWatchSchedule, timeZone: string, token: string) => request<{ id: string; folder_url: string }>(
    "/drive-watch/folders", token, { method: "POST", body: JSON.stringify({ folder_url: folderUrl, schedule, time_zone: timeZone }) },
  ),
  driveInbox: (token: string) => request<DriveWatchInbox>("/drive-watch/inbox", token),
  dismissDriveAlert: (alertId: number, token: string) => request<{ dismissed: boolean }>(
    `/drive-watch/alerts/${alertId}/dismiss`, token, { method: "POST" },
  ),
  createSession: (jobId: string | undefined, token: string, rankingRunId?: string, useSavedRun = true) => request<AgentSession>("/sessions", token, {
    method: "POST", body: JSON.stringify({ job_id: jobId, ranking_run_id: rankingRunId, use_saved_run: useSavedRun }),
  }),
  getSession: (sessionId: string, token: string) => request<AgentSession>(`/sessions/${sessionId}`, token),
  listSessions: (token: string) => request<AgentSessionSummary[]>("/sessions", token),
  deleteSession: (sessionId: string, token: string) => request<void>(`/sessions/${sessionId}`, token, {
    method: "DELETE",
  }),
  send: (sessionId: string, content: string, token: string) => request<{
    session: AgentSession; answer: string; campaign: Campaign | null;
  }>(`/sessions/${sessionId}/messages`, token, { method: "POST", body: JSON.stringify({ content }) }),
  approve: (sessionId: string, revision: number, token: string) => request<{
    campaign: Campaign; delivery_status: "queued";
  }>(`/sessions/${sessionId}/approve`, token, {
    method: "POST", body: JSON.stringify({ expected_revision: revision }),
  }),
  approveQuestions: (sessionId: string, revision: number, token: string) => request<AgentSession>(
    `/sessions/${sessionId}/questions/approve`, token, {
      method: "POST", body: JSON.stringify({ expected_revision: revision }),
    },
  ),
  dispatch: (sessionId: string, token: string) => request<{
    campaign_id: string; status: "scheduled";
  }>(`/sessions/${sessionId}/dispatch`, token, { method: "POST" }),
};
