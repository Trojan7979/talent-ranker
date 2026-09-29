from datetime import UTC, datetime
from uuid import UUID

import pytest
from conftest import RUN_ID, headers, make_config


@pytest.mark.integration
def test_campaign_directory_requires_access_and_paginates_tied_timestamps(client):
    assert client.get("/screening/campaigns").status_code == 401
    config_id = make_config(client)
    ids = []
    for _ in range(2):
        response = client.post(
            "/screening/campaigns",
            headers=headers(),
            json={
                "job_id": "job-1",
                "ranking_run_id": str(RUN_ID),
                "config_id": config_id,
                "rule": {"kind": "top_n", "value": 2},
                "message_template": "Please complete {screening_link}",
            },
        )
        assert response.status_code == 201, response.text
        ids.append(UUID(response.json()["id"]))

    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE screening_campaigns SET created_at=%s WHERE id=ANY(%s)",
            (datetime(2026, 9, 29, tzinfo=UTC), ids),
        )

    first = client.get("/screening/campaigns?limit=1", headers=headers())
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["id"] for item in page["items"]] == [str(max(ids))]
    assert page["items"][0]["candidate_count"] == 2
    second = client.get(
        "/screening/campaigns",
        headers=headers(),
        params={
            "job_id": "job-1",
            "before_created_at": page["next_before_created_at"],
            "before_id": page["next_before_id"],
            "limit": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert [item["id"] for item in second.json()["items"]] == [str(min(ids))]
    assert second.json()["next_before_id"] is None
    assert client.get("/screening/campaigns?job_id=other", headers=headers()).json()["items"] == []
    assert (
        client.get("/screening/campaigns?before_id=" + str(ids[0]), headers=headers()).status_code
        == 422
    )
