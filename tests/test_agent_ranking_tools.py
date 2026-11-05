"""Ranking chat tools keep saved-run reads separate from new ranking jobs."""

import json
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

from sieve_app import agent_runtime


def _runtime(monkeypatch, action, session, ranking_repo, store,
             prompt="Show the saved top 25"):
    class Agent:
        def __init__(self, tools):
            self.tools = {item.name: item for item in tools}

        def invoke(self, payload, config):
            output = action(self.tools)
            if output is None:
                return {"messages": [AIMessage(
                    content="Do you want the saved run or a new ranking?"
                )]}
            return {"messages": [ToolMessage(content=output, tool_call_id="test"),
                                 AIMessage(content="Model summary")]}

    monkeypatch.setattr(agent_runtime, "ChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr(agent_runtime, "create_agent",
                        lambda model, tools, system_prompt: Agent(tools))
    settings = SimpleNamespace(max_tool_calls=12, max_model_turns=8, model="test",
                               api_key="test", base_url="http://localhost", model_timeout_seconds=5,
                               max_retries=0, max_recipients=10)
    runtime = agent_runtime.RecruitmentAgentRuntime(
        settings, None, ranking_repo, store, frozenset({"job-1"})
    )
    return runtime.invoke(session, "recruiter-1", [
        {"role": "user", "content": prompt}
    ])


def test_show_saved_run_reads_25_without_screening_or_queueing(monkeypatch):
    run_id = uuid4()
    session = {"id": uuid4(), "job_id": "job-1", "ranking_run_id": run_id,
               "workspace_id": "workspace-1", "actor_id": "recruiter-1"}
    calls = []
    repo = SimpleNamespace(get_saved_run=lambda *args: (
        calls.append(args) or {"job_id": "job-1", "total_count": 28,
                               "items": [{"candidate_id": "CAND_1", "rank": 1, "score": 0.8}]}
    ))
    store = SimpleNamespace(queue_reranking=lambda *args: calls.append("queued"))

    def action(tools):
        return tools["show_saved_run"].invoke({
            "requested_job_id": "job-1", "ranking_run_id": str(run_id), "top_n": 25,
        })

    assert _runtime(monkeypatch, action, session, repo, store) == "Model summary"
    assert calls == [(str(run_id), 0, 25, "workspace-1", "recruiter-1")]


def test_fresh_ranking_tool_queues_requested_count_and_returns_store_reply(monkeypatch):
    session = {"id": uuid4(), "job_id": "job-1", "ranking_run_id": uuid4(),
               "workspace_id": "workspace-1", "actor_id": "recruiter-1"}
    queued = []
    store = SimpleNamespace(queue_reranking=lambda row, count: (
        queued.append((row, count)) or 3
    ))

    def action(tools):
        result = tools["start_fresh_ranking"].invoke({"top_n": 25})
        assert json.loads(result)["status"] == "queued"
        return result

    reply = _runtime(monkeypatch, action, session, None, store)
    assert queued == [(session, 25)]
    assert "Ranking the top 25" in reply
    assert "criteria version 3" in reply


def test_fresh_ranking_tool_blocks_session_with_screening_work(monkeypatch):
    session = {"id": uuid4(), "job_id": "job-1", "ranking_run_id": uuid4(),
               "workspace_id": "workspace-1", "actor_id": "recruiter-1",
               "question_draft": {"must_haves": ["Python"]}}
    store = SimpleNamespace(queue_reranking=lambda *args: (_ for _ in ()).throw(
        AssertionError("ranking must not be queued")
    ))

    def action(tools):
        result = tools["start_fresh_ranking"].invoke({"top_n": 25})
        assert json.loads(result)["status"] == "blocked"
        return result

    assert "Start a new conversation" in _runtime(monkeypatch, action, session, None, store)


def test_ambiguous_ranking_without_tool_does_not_queue_work(monkeypatch):
    session = {"id": uuid4(), "job_id": "job-1", "ranking_run_id": uuid4(),
               "workspace_id": "workspace-1", "actor_id": "recruiter-1"}
    store = SimpleNamespace(queue_reranking=lambda *args: (_ for _ in ()).throw(
        AssertionError("ranking must not be queued")
    ))
    reply = _runtime(monkeypatch, lambda tools: None, session, None, store,
                     "Could you do something with the ranking?")
    assert "existing saved ranking or calculate a fresh ranking" in reply
