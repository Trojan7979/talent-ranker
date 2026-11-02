import type { Decision, Proposal } from "./SourceProposalReview";

export function selectFirstResumes(proposals: Proposal[], current: Record<string, Decision>, count: number) {
  return Object.fromEntries(proposals.map((item, index) => {
    const eligible = item.suggestion !== "review" && !item.analysis_error;
    const include = index < count && eligible;
    return [item.object_id, {
      ...current[item.object_id],
      object_id: item.object_id,
      action: include ? item.suggestion === "new" ? "new" : "existing" : "skip",
    }];
  })) as Record<string, Decision>;
}
