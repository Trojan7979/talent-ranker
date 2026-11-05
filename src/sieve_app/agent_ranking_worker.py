"""Run recruiter-approved rankings outside chat requests."""

import argparse
import logging
from threading import Event

from candidate_screening.repository import PostgresRepository as ScreeningRepository

from talent_ranker.access import RecruiterScope
from talent_ranker.config import SETTINGS
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.ranking_explanations import RankingExplanationGenerator

from .agent_config import AgentSettings
from .agent_store import AgentStore

logger = logging.getLogger(__name__)


class AgentRankingWorker:
    def __init__(self, store: AgentStore, pipeline: RankingPipeline):
        self.store, self.pipeline = store, pipeline

    def run_once(self) -> bool:
        job = self.store.claim_ranking()
        if job is None:
            return False
        logger.info("Ranking top %s candidates.", job["top_k"])
        logger.debug(
            "Ranking job details: session_id=%s profile_version_id=%s",
            job["session_id"], job["profile_version_id"],
        )
        try:
            profile = self.pipeline.repo.get_job_profile(str(job["profile_version_id"]))
            if profile is None or profile["status"] != "approved":
                raise ValueError("approved job profile is unavailable")
            session = self.store.ranking_session(job["session_id"])
            if session is None:
                raise ValueError("ranking session is unavailable")
            scope = RecruiterScope(
                session["workspace_id"], session["actor_id"],
                frozenset({session["job_id"]}),
            )
            run_id, results = self.pipeline.rank(
                profile["job_id"], profile, job["top_k"], scope,
                progress=lambda message: self.store.update_ranking_progress(job, message),
            )
            self.store.finish_ranking(job, run_id, results)
            logger.info("Ranking completed: %s ranking results saved.", len(results))
            logger.debug(
                "Ranking result details: session_id=%s run_id=%s",
                job["session_id"], run_id,
            )
        except Exception:
            logger.exception("Ranking job failed")
            self.store.fail_ranking(job)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process approved agent ranking jobs")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info(
        "Ranking worker started; %s.",
        "processing one queued job" if args.once else "waiting for ranking requests",
    )
    logger.debug(
        "Ranking worker configuration: poll_interval=%.1fs reranker=%s",
        args.interval, SETTINGS.hosted_reranker_model,
    )
    agent_settings = AgentSettings()
    agent_settings.require_ready()
    pipeline = RankingPipeline(SETTINGS, explanation_generator=RankingExplanationGenerator(
        agent_settings.base_url.rstrip("/") + "/chat/completions",
        agent_settings.api_key.get_secret_value(), agent_settings.model,
        agent_settings.ranking_explanation_timeout_seconds,
    ))
    repo = ScreeningRepository(SETTINGS.database_url)
    try:
        worker = AgentRankingWorker(AgentStore(repo), pipeline)
        stop = Event()
        if args.once:
            worker.run_once()
        else:
            while not stop.is_set():
                if not worker.run_once():
                    stop.wait(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.repo.close()
        repo.close()


if __name__ == "__main__":
    main()
