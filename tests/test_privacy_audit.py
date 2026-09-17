from talent_ranker.privacy_audit import audit_privacy


def test_audit_reports_locations_without_pii_values():
    records = [
        ("CAND_0001", "candidates.raw_text", "Email alex@example.com or call 9876543210"),
        ("CAND_0001", "resume_chunks.content", "Built a customer support workflow"),
        ("CAND_0002", "ranking_results.reasoning", "Visit linkedin.com/in/example-user"),
    ]

    report = audit_privacy(records)

    assert report.affected_candidates == 2
    assert report.finding_count == 3
    assert report.issues[0].candidate_id == "CAND_0001"
    assert report.issues[0].pii_types == ("email", "phone")
    assert "alex@example.com" not in repr(report)
    assert "9876543210" not in repr(report)


def test_audit_returns_empty_report_for_sanitized_content():
    records = [
        ("CAND_0001", "candidates.raw_text", "Contact [REDACTED_EMAIL]"),
        ("CAND_0001", "resume_chunks.content", "Managed customer onboarding"),
    ]

    report = audit_privacy(records)

    assert report.finding_count == 0
    assert report.affected_candidates == 0
    assert not report.issues
