from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sieve_app.evidence_api import router


@pytest.fixture
def client():
    calls = []

    class Store:
        def get_for_candidates(self, ids):
            calls.append(ids)
            return {'CAND_0001': []} if 'CAND_0001' in ids else {}

    app = FastAPI()
    app.state.evidence_store = Store()
    app.state.screening_settings = SimpleNamespace(recruiter_tokens={'secret': 'recruiter'})
    app.include_router(router)
    with TestClient(app) as client:
        yield client, calls


def test_evidence_requires_auth_before_reading_candidate_data(client):
    client, calls = client
    assert client.get('/api/sources/candidates/CAND_0001/evidence').status_code == 401
    assert client.post('/api/sources/evidence/batch', json={'candidate_ids': ['CAND_0001']},
                      headers={'Authorization': 'Bearer wrong'}).status_code == 403
    assert not calls


def test_evidence_reads_are_validated_and_not_cached(client):
    client, calls = client
    headers = {'Authorization': 'Bearer secret'}
    response = client.get('/api/sources/candidates/CAND_0001/evidence', headers=headers)
    assert response.status_code == 200 and response.json() == []
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/sources/candidates/CAND_0002/evidence', headers=headers).status_code == 404
    assert client.get('/api/sources/candidates/invalid/evidence', headers=headers).status_code == 422
    response = client.post('/api/sources/evidence/batch', headers=headers,
                           json={'candidate_ids': ['CAND_0001', 'CAND_0001']})
    assert response.status_code == 200 and calls[-1] == ['CAND_0001']
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.post('/api/sources/evidence/batch', headers=headers,
                        json={'candidate_ids': ['CAND_0001'] * 101}).status_code == 422
