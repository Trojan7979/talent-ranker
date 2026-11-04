import type { CandidateScore } from "./api";

type Criterion = NonNullable<CandidateScore["requirement_evidence"]>[number];

export function criterionLabel(item: Criterion): string {
  if (typeof item.requirement === "string") return item.requirement;
  return Object.values(item.requirement).map(String).join(", ");
}

export function rankingExplanation(candidate: CandidateScore) {
  const criteria = candidate.requirement_evidence ?? [];
  const skillItems = criteria.filter((item) =>
    item.category === "must_have_skills" || item.category === "preferred_skills");
  const matchedSkills = skillItems.filter((item) => item.status !== "not_evidenced")
    .map(criterionLabel);
  const skills = matchedSkills.length
    ? `${matchedSkills.slice(0, 4).join(", ")}${matchedSkills.length > 4 ? `, +${matchedSkills.length - 4} more` : ""} recorded in the resume.`
    : "No approved skill match recorded in the saved evidence.";

  const experience = "Experience years are not available yet; add them later from a verified source.";

  const assessed = criteria.filter((item) =>
    ["must_have_skills", "preferred_skills", "must_have_requirements", "preferred_requirements"].includes(item.category));
  const supported = assessed.filter((item) => item.status !== "not_evidenced").length;
  const why = assessed.length
    ? `Rank #${candidate.rank}: ${supported}/${assessed.length} stated criteria have resume evidence; final order uses BGE semantic relevance.`
    : `Rank #${candidate.rank}: ordered by BGE semantic relevance; no explicit criteria were recorded.`;

  return { skills, experience, why };
}
