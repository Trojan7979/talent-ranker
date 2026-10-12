from sieve_app.resume_identity import corroborated_name, extract_identity


def test_extracts_one_header_email_without_using_resume_body_as_identity():
    text = "Jane Doe\njane@example.com\nSenior engineer\n" + "Experience\n" * 100
    assert extract_identity(text).name == "Jane Doe"
    assert extract_identity(text).email == "jane@example.com"


def test_multiple_header_emails_are_not_silently_matched():
    text = "Jane Doe\njane@example.com\nrecruiter@example.com\n"
    assert extract_identity(text).email is None


def test_headings_and_prose_are_not_candidate_names():
    assert extract_identity("Career Objective\nExperience\n").name is None
    assert extract_identity("challenging marketing sales environment.\nSkills\n").name is None
    assert extract_identity("Senior Software Engineer\nExperience\n").name is None
    assert extract_identity("DR. ASTHA SINGH\nExperience\n").name == "DR. ASTHA SINGH"


def test_unattended_backfill_requires_an_independent_clue():
    assert corroborated_name("Jane Doe", "Jane_Doe_resume", None)
    assert corroborated_name("Jane Doe", "candidate_1", "jane.doe@example.com")
    assert not corroborated_name("Jane Doe", "candidate_1", "recruiter@example.com")
    assert not corroborated_name("Career Objective", "Career_Objective", None)


def test_job_title_requires_an_explicit_header_label():
    identity = extract_identity("Jane Doe\nCurrent role: Senior Software Engineer\njane@example.com")
    assert identity.job_title == "Senior Software Engineer"
    assert identity.name == "Jane Doe"
    assert extract_identity("Jane Doe\nSenior Software Engineer").job_title is None
    assert extract_identity("Jane Doe\n" + "Experience\n" * 12 + "Role: Previous job").job_title is None
