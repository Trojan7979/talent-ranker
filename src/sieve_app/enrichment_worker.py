"""Process external evidence independently of indexing and API requests."""

import argparse
import logging
from threading import Event

from talent_ranker.config import SETTINGS
from talent_ranker.evidence_fetcher import EvidenceFetcher, FetchError, PublicHttpClient
from talent_ranker.external_evidence import EvidenceStore

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    def __init__(self, store: EvidenceStore, fetcher: EvidenceFetcher):
        self.store, self.fetcher = store, fetcher

    def run_once(self) -> bool:
        job = self.store.claim_next()
        if job is None:
            return False
        try:
            evidence = self.fetcher.fetch(job['url'], job['kind'])
        except FetchError as error:
            self.store.fail(job, error.code, retryable=error.retryable, blocked=error.blocked,
                            retry_after=error.retry_after)
        except Exception:  # noqa: BLE001 -- isolate malformed external content per job
            # Exception messages may contain credentials or URLs; retain a safe code only.
            logger.error('Evidence job %s failed during extraction', job['id'])
            self.store.fail(job, 'extraction_error')
        else:
            self.store.complete(job, evidence)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch queued public resume-link evidence')
    parser.add_argument('--once', action='store_true', help='Process at most one queued URL')
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('interval must be positive')
    token = SETTINGS.github_token.get_secret_value() if SETTINGS.github_token else None
    store = EvidenceStore(SETTINGS.database_url)
    try:
        worker = EnrichmentWorker(store, EvidenceFetcher(PublicHttpClient(token)))
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
        store.close()


if __name__ == '__main__':
    main()
