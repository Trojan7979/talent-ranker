from datetime import UTC, datetime
from io import BytesIO

import pytest
from conftest import headers
from openpyxl import load_workbook
from test_candidate_flow import complete_answers
from test_review import sent_batch

from candidate_screening.export import build_workbook


@pytest.mark.integration
def test_selected_completed_export_has_real_workbook_and_no_invite_token(client):
    campaign_id, tokens = sent_batch(client)
    token = tokens["CAND_0001"]
    assert client.post(f"/screening/invites/{token}/started").status_code == 200
    assert (
        client.post(
            f"/screening/invites/{token}/complete",
            json={"expected_revision": 0, "answers": complete_answers()},
        ).status_code
        == 200
    )

    url = f"/screening/campaigns/{campaign_id}/exports"
    assert client.post(url, json={"candidate_ids": ["CAND_0001"]}).status_code == 401
    assert (
        client.post(url, headers=headers(), json={"candidate_ids": ["CAND_0003"]}).status_code
        == 409
    )
    response = client.post(url, headers=headers(), json={"candidate_ids": ["CAND_0001"]})
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"PK")
    sheet = load_workbook(BytesIO(response.content), read_only=True).active
    values = list(sheet.values)
    row = dict(zip(values[0], values[1], strict=True))
    assert len(values) == 2
    assert row["Candidate ID"] == "CAND_0001"
    assert row["Email"] == "cand_0001@example.test"
    assert row["Outcome"] == "proceed_to_interview"
    assert row["Expected salary min"] == 100000
    assert row["Currency"] == "USD"
    assert row["Name"] is None
    assert row["Current CTC"] is None
    assert all(token not in str(value) for cells in values for value in cells if value is not None)


def test_exported_text_cannot_become_spreadsheet_formula():
    row = {
        "candidate_id": "CAND_1",
        "recipient_email": "=2+2",
        "status": "completed",
        "outcome": "needs_recruiter_review",
        "confirmed": [],
        "missing": [],
        "needs_verification": [],
        "interest": None,
        "earliest_start_date": None,
        "notice_days": None,
        "salary_minimum": None,
        "salary_maximum": None,
        "salary_currency": None,
        "salary_period": None,
        "salary_negotiable": False,
        "completed_at": datetime.now(UTC),
    }
    sheet = load_workbook(BytesIO(build_workbook([row]))).active
    assert sheet["C2"].data_type == "s"
    assert sheet["C2"].value == "'=2+2"
