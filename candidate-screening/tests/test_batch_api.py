from conftest import headers, make_config


def test_batch_preparation_reads_latest_config_and_contacts(client):
    assert client.get("/screening/jobs/job-1/latest-config").status_code == 401
    assert client.get("/screening/jobs/job-1/latest-config", headers=headers()).status_code == 404
    config_id = make_config(client)
    config = client.get("/screening/jobs/job-1/latest-config", headers=headers())
    assert config.status_code == 200
    assert config.json()["id"] == config_id

    saved = client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "one@example.test", "source": "test"},
    )
    assert saved.status_code == 200
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO candidate_names(candidate_id,display_name) VALUES ('CAND_0001','Jane Doe')")
    body = {"candidate_ids": ["CAND_0003", "CAND_0001", "CAND_0003"]}
    assert client.post("/screening/contacts/lookup", json=body).status_code == 401
    contacts = client.post("/screening/contacts/lookup", headers=headers(), json=body)
    assert contacts.status_code == 200
    assert contacts.json() == [
        {"candidate_id": "CAND_0003", "display_name": None, "name_source": None,
         "email": None, "contactable": False},
        {"candidate_id": "CAND_0001", "display_name": "Jane Doe", "name_source": "test",
         "email": "one@example.test", "contactable": True},
    ]


def test_recruiter_can_correct_name_without_exposing_it_to_unauthorized_reads(client):
    path = "/screening/candidates/CAND_0001/name"
    assert client.put(path, json={"display_name": "Jane Doe"}).status_code == 401
    assert client.put(path, headers=headers(), json={"display_name": " ",}).status_code == 422
    saved = client.put(path, headers=headers(), json={"display_name": "Jane Doe"})
    assert saved.status_code == 200
    assert saved.json() == {"candidate_id": "CAND_0001", "display_name": "Jane Doe"}
    changed = client.put(path, headers=headers(), json={"display_name": "Jane A. Doe"})
    assert changed.status_code == 200
    lookup = client.post("/screening/contacts/lookup", headers=headers(),
                         json={"candidate_ids": ["CAND_0001"]})
    assert lookup.json()[0]["display_name"] == "Jane A. Doe"
    assert client.put("/screening/candidates/CAND_0002/name", headers=headers(),
                      json={"display_name": "Removed Person"}).status_code == 404
