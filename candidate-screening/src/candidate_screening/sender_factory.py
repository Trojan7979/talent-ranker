"""Build the configured initial-invitation sender for API and CLI workers."""

from .config import Settings
from .email import EmailSender, FakeEmailSender, SmtpEmailSender
from .gmail import GmailApiSender


def create_sender(settings: Settings) -> EmailSender:
    if settings.sender_backend == "fake":
        return FakeEmailSender()
    if settings.sender_backend == "smtp":
        if not settings.smtp_host or not settings.smtp_from_email:
            raise ValueError("SMTP sender is not configured")
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            from_email=settings.smtp_from_email,
            username=settings.smtp_username,
            password=settings.smtp_password,
        )
    if settings.sender_backend == "gmail_api":
        if not settings.gmail_sender_email:
            raise ValueError("Gmail sender address is not configured")
        if not settings.gmail_token_file.is_file():
            raise ValueError("Gmail sender is not authorized; run authorize-gmail")
        return GmailApiSender(settings.gmail_sender_email, settings.gmail_token_file)
    raise ValueError("SCREENING_SENDER_BACKEND must be fake, smtp, or gmail_api")
