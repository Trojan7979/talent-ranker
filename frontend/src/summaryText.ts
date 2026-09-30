const followUp: Record<string, string> = {
  interest: "Interest needs clarification",
  availability: "Start date needs clarification",
  notice_period: "Notice period needs clarification",
  salary: "Salary expectation needs clarification",
  availability_after_target: "Start date is after the target date",
  notice_exceeds_limit: "Notice period exceeds the job's limit",
  availability_notice_conflict: "Start date and notice period may conflict",
  salary_not_comparable: "Salary uses a different currency or pay period",
  salary_above_budget: "Expected salary is above the job budget",
  salary_partly_above_budget: "Expected range overlaps the job budget",
};

const requirement = (id: string, labels: Record<string, string>) =>
  labels[id] ?? id.replace(/[-_]/g, " ");

function reportedRequirement(label: string): string {
  if (/^Experience /i.test(label)) return `Reports ${label[0].toLowerCase()}${label.slice(1)}`;
  if (/^Strong understanding of /i.test(label)) return `Reports a ${label[0].toLowerCase()}${label.slice(1)}`;
  return `Reports experience with ${label}`;
}

export function summaryText(values: string[], kind: "reported" | "missing" | "followUp",
  labels: Record<string, string>): string[] {
  return values.map((value) => {
    if (kind === "reported") {
      if (value === "candidate_confirmed:interest") return "Interested in the role";
      if (value.startsWith("candidate_confirmed:"))
        return reportedRequirement(requirement(value.slice(20), labels));
      if (value.startsWith("candidate_reported:availability:"))
        return `Earliest start: ${value.split(":").at(-1)}`;
      if (value.startsWith("candidate_reported:notice_period_days:"))
        return `Notice period: ${value.split(":").at(-1)} days`;
      if (value.startsWith("candidate_reported:salary_expectation:"))
        return `Expected salary: ${value.slice(38)}`;
    }
    if (kind === "missing") {
      if (value.startsWith("qualification:"))
        return `${requirement(value.slice(14), labels)}: no answer`;
      return `${value.replaceAll("_", " ")}: no answer`;
    }
    if (kind === "followUp") {
      if (value.startsWith("qualification:")) {
        const [, id, answer] = value.split(":");
        return `${requirement(id, labels)}: ${answer === "no" ? "candidate said no" : "candidate is unsure"}`;
      }
      return followUp[value] ?? value.replaceAll("_", " ");
    }
    return value.replaceAll("_", " ");
  });
}
