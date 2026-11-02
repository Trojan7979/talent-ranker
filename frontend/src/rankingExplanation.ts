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

  const years = criteria.find((item) => item.category === "minimum_years_experience");
  const experience = years?.reported_value != null
    ? `${years.reported_value} years reported; JD minimum ${criterionLabel(years)} years. Not independently verified.`
    : years
      ? `JD minimum ${criterionLabel(years)} years; candidate total not verified from saved evidence.`
      : "Total years of experience not verified from saved evidence.";

  const assessed = criteria.filter((item) =>
    ["must_have_skills", "preferred_skills", "must_have_requirements", "preferred_requirements"].includes(item.category));
  const supported = assessed.filter((item) => item.status !== "not_evidenced").length;
  const why = assessed.length
    ? `Rank #${candidate.rank}: ${supported}/${assessed.length} stated criteria have resume evidence; final order also uses semantic and retrieval relevance.`
    : `Rank #${candidate.rank}: ordered by semantic and retrieval relevance; no explicit criteria were recorded.`;

  return { skills, experience, why };
}
