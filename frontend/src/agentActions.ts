export const agentActions = [
  { id: "role", label: "Start a new role", description: "Draft a JD and approve criteria in chat.", prompt: "Write a JD for a senior backend engineer building Python APIs and PostgreSQL systems. Include mentoring; location and salary are to confirm." },
  { id: "runs", label: "Saved ranking runs", description: "Find recent runs for the active job.", prompt: "List the recent saved ranking runs for this job." },
  { id: "preview", label: "Preview candidates", description: "Review up to 10 candidates from a saved run.", prompt: "Preview the top 5 candidates from this saved ranking run and show their scores." },
  { id: "screening", label: "Prepare screening", description: "Draft questions for recruiter approval.", prompt: "Draft screening questions for the top 4 candidates from the approved hiring criteria. Do not approve or send invitations." },
  { id: "status", label: "Campaign status", description: "Check a campaign and its invitations.", prompt: "Check the screening campaign status and invitation delivery for this session. If there is no campaign yet, tell me." },
] as const;
