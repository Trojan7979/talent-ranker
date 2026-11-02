"""Chat-led question draft from approved hiring criteria; no outreach side effects."""

import re
from uuid import UUID

from candidate_screening.questions import draft_questions


class AgentScreeningWorkflow:
    def __init__(self, screening_repo, store, max_recipients: int):
        self.repo = screening_repo
        self.store = store
        self.max_recipients = max_recipients

    @staticmethod
    def is_draft_request(message: str) -> bool:
        return bool(re.search(
            r"\b(?:draft|create|generate|write|prepare)\b.{0,80}\bscreening questions\b",
            message, re.IGNORECASE,
        ))

    def draft(self, session: dict, message: str) -> str:
        if session["campaign_id"] or session.get("question_config_id"):
            return "This session already has an approved question set or campaign. Open a new saved-run conversation for a different set."
        match = re.search(r"\btop\s+(\d{1,3})\b", message, re.IGNORECASE)
        top_n = int(match.group(1)) if match else 10
        if not 1 <= top_n <= self.max_recipients:
            return f"Choose between 1 and {self.max_recipients} candidates for screening."
        run = self.repo.resolve_run(session["job_id"], UUID(str(session["ranking_run_id"])))
        if run is None or run["profile_status"] != "approved":
            raise ValueError("saved ranking run needs approved hiring criteria")
        profile_id = run["job_profile_version_id"]
        priorities = self.repo.approved_profile_priorities(session["job_id"], profile_id)
        if priorities is None:
            raise ValueError("approved hiring criteria are unavailable")
        questions = draft_questions(priorities)
        latest = self.repo.latest_job_config(session["job_id"])
        questions.version = latest["version"] + 1 if latest else 1
        saved = self.store.save_question_draft(session["id"], profile_id, top_n, questions)
        if saved is None:
            raise ValueError("this session can no longer accept a question draft")
        return (
            f"I drafted screening questions from the approved criteria for the top {top_n}. "
            "Review them in the question approval card. Approval saves the questions and "
            "prepares a campaign for recipient review; it does not send email."
        )
