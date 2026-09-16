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

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function rankCandidates(
  jobId: string,
  jobDescription: string,
  topK = 20,
): Promise<RankResponse> {
  const response = await fetch(`${apiBaseUrl}/rank`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, job_description: jobDescription, top_k: topK }),
  });

  if (!response.ok) {
    throw new Error(`Ranking request failed with HTTP ${response.status}`);
  }

  return response.json();
}
