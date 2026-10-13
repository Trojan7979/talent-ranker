export type AgentMessage = { id: number; role: "user" | "assistant"; content: string; created_at: string };
export type AgentSession = {
  id: string; job_id: string; ranking_run_id: string | null; campaign_id: string | null;
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
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json();
}

export const agentApi = {
  createSession: (jobId: string, token: string) => request<AgentSession>("/sessions", token, {
    method: "POST", body: JSON.stringify({ job_id: jobId }),
  }),
  getSession: (sessionId: string, token: string) => request<AgentSession>(`/sessions/${sessionId}`, token),
  send: (sessionId: string, content: string, token: string) => request<{
    session: AgentSession; answer: string; campaign: Campaign | null;
  }>(`/sessions/${sessionId}/messages`, token, { method: "POST", body: JSON.stringify({ content }) }),
  approve: (sessionId: string, revision: number, token: string) => request<{
    campaign: Campaign; delivery_status: "queued";
  }>(`/sessions/${sessionId}/approve`, token, {
    method: "POST", body: JSON.stringify({ expected_revision: revision }),
  }),
};
