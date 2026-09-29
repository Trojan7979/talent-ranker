import os
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from sieve_app.workflow import CampaignWorkflow


def test_campaign_observer_resumes_from_recruiter_gate_without_mutating_domain():
    campaign_id = uuid4()

    class Repository:
        def __init__(self):
            self.campaign = {"status": "proposed", "revision": 1}
            self.reads = 0

        def get_campaign(self, requested_id):
            assert requested_id == campaign_id
            self.reads += 1
            return self.campaign

    repository = Repository()
    checkpoint = InMemorySaver()
    first_process = CampaignWorkflow(repository, checkpoint)
    assert first_process.sync(campaign_id)["workflow_status"] == "waiting_for_recruiter"
    assert first_process.status(campaign_id)["revision"] == 1

    repository.campaign = {"status": "approved", "revision": 2}
    restarted_process = CampaignWorkflow(repository, checkpoint)
    status = restarted_process.sync(campaign_id)
    assert status["campaign_status"] == "approved"
    assert status["revision"] == 2
    assert status["workflow_status"] == "observed"
    assert restarted_process.sync(campaign_id) == status
    assert repository.reads == 2


@pytest.mark.integration
def test_campaign_observer_survives_postgres_checkpoint_restart():
    database_url = os.getenv("TALENT_RANKER_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set TALENT_RANKER_TEST_DATABASE_URL for checkpoint persistence test")
    schema = "workflow_test_" + uuid4().hex
    campaign_id = uuid4()

    class Repository:
        campaign = None

        def get_campaign(self, requested_id):
            assert requested_id == campaign_id
            return self.campaign

    repository = Repository()
    repository.campaign = {"status": "proposed", "revision": 1}
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            checkpoint_url = f"{database_url}?options=-csearch_path%3D{schema}"
            with PostgresSaver.from_conn_string(checkpoint_url) as checkpoint:
                checkpoint.setup()
                assert CampaignWorkflow(repository, checkpoint).sync(campaign_id)[
                    "workflow_status"
                ] == "waiting_for_recruiter"

            repository.campaign = {"status": "approved", "revision": 2}
            with PostgresSaver.from_conn_string(checkpoint_url) as checkpoint:
                status = CampaignWorkflow(repository, checkpoint).sync(campaign_id)
                assert status["campaign_status"] == "approved"
                assert status["revision"] == 2
                assert status["workflow_status"] == "observed"
        finally:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
