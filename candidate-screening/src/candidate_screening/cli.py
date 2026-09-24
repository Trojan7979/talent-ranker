import argparse
from uuid import UUID

from .config import Settings
from .delivery import InitialInviteDispatcher
from .email import FakeEmailSender, SmtpEmailSender
from .gmail import GmailApiSender, authorize_gmail
from .repository import PostgresRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate screening background jobs")
    parser.add_argument("command", choices=["dispatch", "expire", "authorize-gmail"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--campaign-id", type=UUID)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    settings = Settings()
    if args.command == "authorize-gmail":
        if not settings.gmail_client_secrets_file:
            parser.error("SCREENING_GMAIL_CLIENT_SECRETS_FILE is required")
        authorize_gmail(settings.gmail_client_secrets_file, settings.gmail_token_file)
        print("Gmail sender authorized")
        return
    if args.command == "expire":
        repo = PostgresRepository(settings.database_url)
        try:
            print({"expired": repo.expire_due()})
        finally:
            repo.close()
        return
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
    elif settings.sender_backend == "gmail_api":
        if not settings.gmail_sender_email:
            parser.error("SCREENING_GMAIL_SENDER_EMAIL is required")
        if not args.campaign_id:
            parser.error("Gmail dispatch requires --campaign-id")
        sender = GmailApiSender(settings.gmail_sender_email, settings.gmail_token_file)
    else:
        parser.error("SCREENING_SENDER_BACKEND must be fake, smtp, or gmail_api")
    repo = PostgresRepository(settings.database_url)
    try:
        print(InitialInviteDispatcher(repo, sender).run_once(args.limit, args.campaign_id))
    finally:
        repo.close()
