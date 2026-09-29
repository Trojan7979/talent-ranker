export type CampaignSummary = {
  id: string;
  job_id: string;
  ranking_run_id: string;
  status: "proposed" | "approved" | "rejected";
  created_at: string;
  candidate_count: number;
};

export type CampaignCursor = { createdAt: string; id: string };

export type CampaignDirectory = {
  items: CampaignSummary[];
  next_before_created_at: string | null;
  next_before_id: string | null;
};

export async function listCampaigns(
  token: string,
  jobId: string | null,
  cursor: CampaignCursor | null,
  signal?: AbortSignal,
): Promise<CampaignDirectory> {
  const query = new URLSearchParams({ limit: "25" });
  if (jobId) query.set("job_id", jobId);
  if (cursor) {
    query.set("before_created_at", cursor.createdAt);
    query.set("before_id", cursor.id);
  }
  const response = await fetch(`/api/screening/campaigns?${query}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json();
}
