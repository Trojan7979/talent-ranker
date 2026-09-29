"""Poll the durable invitation outbox independently of API process lifetimes."""

import argparse
import logging
from threading import Event

from .config import Settings
from .delivery import InitialInviteDispatcher
from .repository import PostgresRepository
from .sender_factory import create_sender

logger = logging.getLogger(__name__)


def serve(dispatcher: InitialInviteDispatcher, stop: Event, interval: float, batch_size: int) -> None:
    """Drain bounded batches; the repository arbitrates concurrent workers."""
    while not stop.is_set():
        counts = dispatcher.run_once(batch_size)
        if any(counts.values()):
            logger.info("Invitation dispatch: %s", counts)
        if sum(counts.values()) < batch_size:
            stop.wait(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued screening invitations")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval <= 0 or args.batch_size <= 0:
        parser.error("interval and batch-size must be positive")

    settings = Settings()
    sender = create_sender(settings)
    repository = PostgresRepository(settings.database_url)
    dispatcher = InitialInviteDispatcher(repository, sender)
    try:
        if args.once:
            logger.info("Invitation dispatch: %s", dispatcher.run_once(args.batch_size))
        else:
            serve(dispatcher, Event(), args.interval, args.batch_size)
    except KeyboardInterrupt:
        pass
    finally:
        repository.close()


if __name__ == "__main__":
    main()
