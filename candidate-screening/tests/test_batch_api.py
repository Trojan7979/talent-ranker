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
    body = {"candidate_ids": ["CAND_0003", "CAND_0001", "CAND_0003"]}
    assert client.post("/screening/contacts/lookup", json=body).status_code == 401
    contacts = client.post("/screening/contacts/lookup", headers=headers(), json=body)
    assert contacts.status_code == 200
    assert contacts.json() == [
        {"candidate_id": "CAND_0003", "email": None, "contactable": False},
        {"candidate_id": "CAND_0001", "email": "one@example.test", "contactable": True},
    ]
