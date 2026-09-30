const acronyms = new Set(["AI", "API", "AWS", "GCP", "HR", "LLM", "ML", "NLP", "QA", "RAG", "SQL", "SRE", "UI", "UX"]);

export function roleTitleFromJobId(jobId: string): string {
  const words = jobId.replace(/(?:[_\s-]+\d+)+$/, "").split(/[_\s-]+/).filter(Boolean);
  return words.map((word) => {
    const upper = word.toUpperCase();
    return acronyms.has(upper) ? upper : upper[0] + word.slice(1).toLowerCase();
  }).join(" ") || "Open Position";
}

export function invitationMessage(roleTitle: string): string {
  return `Hello,

You have been invited to complete a short screening for the ${roleTitle.trim() || "open position"} role. Please use your personal link before it expires:

{screening_link}

Thank you,
Recruitment Team`;
}
