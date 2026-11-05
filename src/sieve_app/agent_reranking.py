"""Queue repeat rankings in an existing recruiter conversation."""


class AgentRerankingWorkflow:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def has_screening_work(session: dict) -> bool:
        return bool(session.get("question_draft") or session.get("question_config_id")
                    or session.get("campaign_id"))

    def queue(self, session: dict, top_k: int) -> str:
        if not 1 <= top_k <= 1000:
            raise ValueError("Choose between 1 and 1000 candidates")
        if self.has_screening_work(session):
            return ("This conversation has screening work attached to its current run. "
                    "Start a new conversation for a fresh ranking so recipients and "
                    "questions stay tied to the original shortlist.")
        version = self.store.queue_reranking(session, top_k)
        return (f"Ranking the top {top_k} from your currently indexed resumes using "
                f"approved criteria version {version}. The earlier saved run remains available; "
                "I will post the new shortlist here when it finishes.")
