from talent_ranker.privacy import detect_pii, redact_pii
from talent_ranker.ranking import build_reasoning, evidence_snippet


def test_detects_supported_contact_identifiers():
    text = "Email alex@example.com, call +91 98765 43210, or visit linkedin.com/in/alex-doe."

    assert [finding.kind for finding in detect_pii(text)] == [
        "email",
        "phone",
        "profile_url",
    ]


def test_redacts_contact_identifiers_without_removing_job_evidence():
    text = (
        "Customer support specialist alex@example.com 9876543210 "
        "managed onboarding and customer queries."
    )

    redacted = redact_pii(text)

    assert "alex@example.com" not in redacted
    assert "9876543210" not in redacted
    assert "managed onboarding and customer queries" in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_evidence_and_reasoning_do_not_expose_contact_details():
    text = "Contact alex@example.com or 9876543210. Managed customer onboarding and retention."

    evidence = evidence_snippet(text, {"contact"})
    reasoning = build_reasoning(["Call 9876543210 for customer support experience"], [], 0.8)

    assert "alex@example.com" not in evidence
    assert "9876543210" not in evidence
    assert "9876543210" not in reasoning
    assert "[REDACTED_PHONE]" in reasoning


def test_does_not_redact_employment_dates_or_short_numbers():
    text = "Worked from 2021-01-01 to 2023-08-15 and exceeded the target by 120%."

    assert redact_pii(text) == text
