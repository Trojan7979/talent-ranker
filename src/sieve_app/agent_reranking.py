"""Explicit repeat ranking in an existing recruiter conversation."""

import re


class AgentRerankingWorkflow:
    REQUEST = re.compile(
        r"^(?:please\s+)?(?:re-?rank|rank)\s+(?:the\s+)?top\s+(\d{1,4})\s+"
        r"candidates?\b", re.IGNORECASE,
    )

    def __init__(self, store):
        self.store = store

    @classmethod
    def is_request(cls, message: str) -> bool:
        return cls.REQUEST.match(message.strip()) is not None

    def handle(self, session: dict, message: str) -> str:
        match = self.REQUEST.match(message.strip())
        if match is None:
            raise ValueError("Ask to rank the top N candidates")
        top_k = int(match.group(1))
        if not 1 <= top_k <= 1000:
            raise ValueError("Choose between 1 and 1000 candidates")
        if (session.get("question_draft") or session.get("question_config_id")
                or session.get("campaign_id")):
            return ("This conversation has screening work attached to its current run. "
                    "Start a new conversation for a fresh ranking so recipients and "
                    "questions stay tied to the original shortlist.")
        version = self.store.queue_reranking(session, top_k)
        return (f"Ranking the top {top_k} from your currently indexed resumes using "
                f"approved criteria version {version}. The earlier saved run remains available; "
                "I will post the new shortlist here when it finishes.")
