import type { CandidateScore } from "./api";

/** New runs store model-written, evidence-grounded bullets in reasoning. */
export function rankingBullets(candidate: CandidateScore): string[] {
  const saved = candidate.reasoning?.split(/\r?\n/)
    .map((line) => line.match(/^\s*[-•]\s+(.+)$/)?.[1]?.trim())
    .filter((line): line is string => Boolean(line)) ?? [];
  if (saved.length) return saved.slice(0, 4);

  // Older runs predate model-written explanations. Only show cited evidence.
  const cited = candidate.requirement_evidence?.filter((item) =>
    (item.status === "supported" || item.status === "partial") && item.passage) ?? [];
  return cited.slice(0, 3).map((item) =>
    item.status === "partial"
      ? `Related experience appears in the resume: ${item.passage}`
      : `Resume evidence: ${item.passage}`);
}
