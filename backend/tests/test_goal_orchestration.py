import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.ai.openrouter import OpenRouterClient
from app.api.routes import chat as chat_route
from app.config import settings
from app.database.models import AgentCheckpoint, AgentEvent, AgentRun
from app.main import app


async def _auth_headers(client, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-strong-password-123", "name": "Test User"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "a-strong-password-123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_multi_step_goal_is_planned_and_uses_previous_step_result(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("response_format"):
            assert body["response_format"] == {"type": "json_object"}
            content = '{"steps":["Calculate 2 + 3","Summarize the result"]}'
        elif len(requests) == 2:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call-calculate",
                                "type": "function",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"2 + 3"}',
                                },
                            }],
                        },
                    }],
                },
            )
        elif len(requests) == 3:
            assert body["messages"][-1]["role"] == "tool"
            assert json.loads(body["messages"][-1]["content"]) == {"value": 5}
            content = "The calculator tool returned 5."
        else:
            assert any(
                message.get("content", "").find("calculator tool returned 5") >= 0
                for message in body["messages"]
                if isinstance(message.get("content"), str)
            )
            content = "Summary: the calculation result is 5."
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    headers = await _auth_headers(client, "multi-step@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Research this and then calculate it and summarize the findings"},
    )

    assert response.status_code == 200
    assert response.json()["reply"].startswith("Summary:")
    assert len(requests) == 4
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, response.json()["run_id"])
        checkpoint = await session.scalar(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run.id,
                AgentCheckpoint.checkpoint_key == "plan-created",
            )
        )
        event_types = list(
            await session.scalars(
                select(AgentEvent.event_type)
                .where(AgentEvent.agent_run_id == run.id)
                .order_by(AgentEvent.sequence)
            )
        )
        plan = run.state_snapshot["plan"]
        assert [step["status"] for step in plan] == ["completed", "completed"]
        assert run.state_snapshot["tool_calls"] == 1
        assert checkpoint is not None
        assert event_types.count("plan.step.started") == 2
        assert event_types.count("plan.step.completed") == 2


@pytest.mark.asyncio
async def test_model_call_limit_returns_transparent_partial_status(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    monkeypatch.setattr(settings, "agent_max_model_calls", 1)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"steps":["One","Two"]}'}}]},
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    headers = await _auth_headers(client, "limited-run@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Research this and then summarize it"},
    )

    assert response.status_code == 200
    assert "batas jumlah panggilan model" in response.json()["reply"]
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, response.json()["run_id"])
        event_types = list(
            await session.scalars(
                select(AgentEvent.event_type).where(AgentEvent.agent_run_id == run.id)
            )
        )
        assert run.status == "limit_reached"
        assert "workflow.limited" in event_types


@pytest.mark.asyncio
async def test_reported_provider_cost_stops_subsequent_model_calls(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    monkeypatch.setattr(settings, "agent_max_cost_usd", 0.05)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": '{"steps":["One","Two"]}'}}],
                "usage": {"cost": 0.06},
            },
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    headers = await _auth_headers(client, "cost-limit@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Research this and then summarize it"},
    )

    assert response.status_code == 200
    assert calls == 1
    assert "batas biaya yang dilaporkan provider" in response.json()["reply"]


@pytest.mark.asyncio
async def test_context_limit_blocks_provider_request(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_max_context_chars", 5000)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    headers = await _auth_headers(client, "context-limit@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "A" * 6000},
    )

    assert response.status_code == 200
    assert "batas ukuran konteks" in response.json()["reply"]
    assert calls == 0


@pytest.mark.asyncio
async def test_failed_provider_attempt_consumes_persistent_call_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    monkeypatch.setattr(settings, "agent_max_model_calls", 1)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    headers = await _auth_headers(client, "failed-budget@example.com")
    failed = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "A simple request"},
    )
    assert failed.status_code == 502

    async with app.state.test_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.status == "failed"))
        assert run is not None
        run_id = run.id
    recovered = await client.post(f"/api/v1/agents/runs/{run_id}/resume", headers=headers)
    assert recovered.status_code == 200
    assert "batas jumlah panggilan model" in recovered.json()["reply"]
    assert calls == 1


@pytest.mark.asyncio
async def test_run_stop_endpoint_is_owner_scoped_and_idempotent(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Finished"}}]},
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    owner_headers = await _auth_headers(client, "run-owner@example.com")
    other_headers = await _auth_headers(client, "run-other@example.com")
    chat = await client.post(
        "/api/v1/chat",
        headers=owner_headers,
        json={"message": "A simple request"},
    )
    run_id = chat.json()["run_id"]
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        run.status = "running"
        await session.commit()

    denied = await client.post(f"/api/v1/agents/runs/{run_id}/stop", headers=other_headers)
    assert denied.status_code == 404
    stopped = await client.post(f"/api/v1/agents/runs/{run_id}/stop", headers=owner_headers)
    repeated = await client.post(f"/api/v1/agents/runs/{run_id}/stop", headers=owner_headers)
    assert stopped.status_code == 202
    assert repeated.status_code == 202
    assert stopped.json() == {"status": "cancel_requested"}
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "cancel_requested"


@pytest.mark.asyncio
async def test_stop_cancels_an_in_flight_model_request(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    request_started = asyncio.Event()
    request_cancelled = asyncio.Event()

    class BlockingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            request_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                request_cancelled.set()
                raise

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=BlockingTransport()),
    )
    headers = await _auth_headers(client, "cancel-run@example.com")
    chat_task = asyncio.create_task(
        client.post("/api/v1/chat", headers=headers, json={"message": "A request that will be stopped"})
    )
    await asyncio.wait_for(request_started.wait(), timeout=5)

    async with app.state.test_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.status == "running"))
        assert run is not None
        run_id = run.id

    stopped = await client.post(f"/api/v1/agents/runs/{run_id}/stop", headers=headers)
    assert stopped.status_code == 202
    response = await asyncio.wait_for(chat_task, timeout=5)
    assert response.status_code == 200
    assert "dihentikan atas permintaanmu" in response.json()["reply"].lower()
    assert request_cancelled.is_set()
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "cancelled"
        event_types = list(
            await session.scalars(
                select(AgentEvent.event_type).where(AgentEvent.agent_run_id == run_id)
            )
        )
        assert "workflow.cancelled" in event_types
