export type ResumeSource = {
  file_name: string;
  web_url: string;
  modified_at: string;
  source_status: "unchanged" | "changed" | "unknown";
};

export async function sourceRequest<T>(
  path: string, token: string, body?: object, signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/sources${path}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : `HTTP ${response.status}`);
  }
  return response.json();
}
