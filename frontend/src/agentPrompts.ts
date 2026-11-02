import type { AgentSession } from "./agentApi";

type Prompt = { label: string; prompt: string };

const jd: Prompt[] = [
  { label: "Draft a JD", prompt: "Write a JD" },
  { label: "Ask what details you need", prompt: "What details do you need to draft a job description?" },
  { label: "Paste my JD", prompt: "I have a JD to paste" },
];
const jdReview: Prompt[] = [
  { label: "Show JD", prompt: "Show JD" },
  { label: "Approve JD", prompt: "I approve this JD" },
  { label: "Turn notes into JD", prompt: "Write a JD from these notes" },
  { label: "Redraft JD", prompt: "Write a JD" },
];
const criteria: Prompt[] = [
  { label: "Review criteria", prompt: "Show criteria" },
  { label: "Change must-haves", prompt: "Change must-have skills to Python, SQL, FastAPI" },
  { label: "Change preferences", prompt: "Change preferred skills to AWS, Docker, Kubernetes" },
  { label: "Change requirements", prompt: "Change must-have requirements to Production API experience, Database design experience" },
  { label: "Approve top 5", prompt: "I approve these criteria; rank top 5 candidates" },
  { label: "Approve top 10", prompt: "I approve these criteria; rank top 10 candidates" },
];
const ranking: Prompt[] = [
  { label: "Check progress", prompt: "Is the shortlist ready yet?" },
];
const ranked: Prompt[] = [
  { label: "Fresh top 12 ranking", prompt: "Rank top 12 candidates using the currently indexed resumes and approved criteria." },
  { label: "Top 10", prompt: "Show the top 10 candidates from this saved run with their scores." },
  { label: "Top 5", prompt: "Show the top 5 candidates and their scores." },
  { label: "Explain #1", prompt: "Why did the top-ranked candidate score highest? Use the saved score components and evidence." },
  { label: "Compare top two", prompt: "Compare the top two candidates using their scores, requirements, and supporting evidence." },
  { label: "Must-haves", prompt: "Which must-have requirements are evidenced for the top candidate?" },
  { label: "Gaps", prompt: "What required skills or experience are missing from the top candidate's saved evidence?" },
  { label: "Score components", prompt: "Break down the top candidate's score components." },
  { label: "Evidence passages", prompt: "Show the saved resume passages supporting the top candidate's ranking." },
  { label: "Linked evidence", prompt: "Inspect the top candidate's fetched GitHub or portfolio evidence and its fetch status. Keep it separate from the ranking score." },
  { label: "Runner-up", prompt: "Why did the second-ranked candidate score below the first?" },
  { label: "Close scores", prompt: "Are the top two candidates close in score? Explain the differences using persisted results." },
  { label: "Candidate count", prompt: "How many candidates are in this saved shortlist?" },
  { label: "Recent runs", prompt: "List recent saved ranking runs for this job." },
  { label: "Draft questions for top 10", prompt: "Draft screening questions for the top 10 candidates from the approved hiring criteria. Do not approve or send invitations." },
  { label: "Draft questions for top 4", prompt: "Draft screening questions for the top 4 candidates from the approved hiring criteria. Do not approve or send invitations." },
  { label: "Screening draft", prompt: "Draft screening questions for the top 4 candidates from the approved hiring criteria. Do not approve or send invitations." },
  { label: "Campaign status", prompt: "Check the current screening campaign status." },
  { label: "Delivery status", prompt: "Which campaign invitations have been sent, failed, or are still pending?" },
  { label: "Before screening", prompt: "Which candidates would be included if I prepared a screening draft for the top 5? Preview only." },
];

export const agentPrompts = {
  forSession(session: AgentSession): Prompt[] {
    const last = session.messages.at(-1);
    const previous = session.messages.at(-2);
    const failedJdApproval = last?.role === "assistant"
      && previous?.role === "user"
      && previous.content.trim().toLowerCase() === "i approve this jd"
      && (last.content.startsWith("I couldn't extract hiring criteria")
        || last.content.startsWith("I could not complete that request"));
    switch (session.setup_stage) {
      case "awaiting_jd": return jd;
      case "awaiting_jd_approval": return failedJdApproval
        ? [jdReview[0],
           { label: "Retry criteria extraction", prompt: "I approve this JD" },
           { label: "Revise JD", prompt: "Replace JD: " },
           jdReview[2]]
        : jdReview;
      case "awaiting_criteria_approval": return criteria;
      case "ranking": return session.ranking_status === "failed"
        ? [{ label: "Retry ranking", prompt: "Retry ranking" }]
        : ranking;
      case "ranked": return ranked;
    }
  },
};
