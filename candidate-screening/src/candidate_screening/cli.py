import argparse

from .config import Settings
from .delivery import InitialInviteDispatcher
from .email import FakeEmailSender, SmtpEmailSender
from .repository import PostgresRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate screening background jobs")
    parser.add_argument("command", choices=["dispatch", "expire"])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.command != "dispatch":
        parser.error("expiry sweep is not available until its implementation step")
    settings = Settings()
    if settings.sender_backend == "fake":
        sender = FakeEmailSender()
    elif settings.sender_backend == "smtp":
        if not settings.smtp_host or not settings.smtp_from_email:
            parser.error("SMTP requires SCREENING_SMTP_HOST and SCREENING_SMTP_FROM_EMAIL")
        sender = SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            from_email=settings.smtp_from_email,
            username=settings.smtp_username,
            password=settings.smtp_password,
        )
    else:
        parser.error("SCREENING_SENDER_BACKEND must be fake or smtp")
    repo = PostgresRepository(settings.database_url)
    try:
        print(InitialInviteDispatcher(repo, sender).run_once())
    finally:
        repo.close()
