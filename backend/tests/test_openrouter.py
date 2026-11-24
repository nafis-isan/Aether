import json

import httpx
import pytest

from app.ai.model_router import resolve_model
from app.ai.openrouter import OpenRouterClient, OpenRouterError
from app.config import settings


@pytest.mark.asyncio
async def test_reasoning_details_are_returned_without_modification(monkeypatch):
    reasoning_details = [{"type": "opaque", "payload": {"signature": "unchanged"}}]
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["reasoning"] == {"enabled": True}
        return httpx.Response(
            200,
            json={
                "model": "cohere/north-mini-code:free",
                "choices": [{"message": {"content": "There are three r's.", "reasoning_details": reasoning_details}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.complete(
        model="cohere/north-mini-code:free",
        messages=[{"role": "user", "content": "Count r's"}],
    )
    assert result["content"] == "There are three r's."
    assert result["reasoning_details"] == reasoning_details
    assert result["usage"]["prompt_tokens"] == 10


@pytest.mark.asyncio
async def test_rate_limit_retries_then_succeeds(monkeypatch):
    attempts = 0
    delays = []
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 1)

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ready"}}]})

    client = OpenRouterClient(transport=httpx.MockTransport(handler), sleep=no_wait)
    result = await client.complete(model="model", messages=[{"role": "user", "content": "Hi"}])
    assert result["content"] == "Ready"
    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_retry_callback_and_citations_are_exposed(monkeypatch):
    attempts = 0
    retries = []
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 1)

    async def no_wait(_: float) -> None:
        return None

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Research answer"}}],
                "citations": [{"title": "Example", "url": "https://example.com/source"}],
            },
        )

    async def on_retry(attempt: int, reason: str) -> None:
        retries.append((attempt, reason))

    client = OpenRouterClient(transport=httpx.MockTransport(handler), sleep=no_wait)
    result = await client.complete(
        model="model",
        messages=[{"role": "user", "content": "Hi"}],
        on_retry=on_retry,
    )
    assert retries == [(1, "rate_limited")]
    assert result["citations"] == [{"title": "Example", "url": "https://example.com/source", "snippet": None, "provider": None}]


@pytest.mark.asyncio
async def test_unauthorized_provider_response_is_not_retried(monkeypatch):
    attempts = 0
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 2)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    with pytest.raises(OpenRouterError) as error:
        await client.complete(model="model", messages=[{"role": "user", "content": "Hi"}])
    assert error.value.code == "invalid_api_key"
    assert attempts == 1


@pytest.mark.asyncio
async def test_streaming_completion_delivers_text_and_usage(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    chunks = [
        {
            "model": "stream-model",
            "choices": [{"delta": {"content": "Hello ", "reasoning_details": [{"type": "opaque", "id": "r1"}]}}],
        },
        {"model": "stream-model", "choices": [{"delta": {"content": "world."}}]},
        {
            "model": "stream-model",
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10, "cost": 0.001},
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body.encode(),
        )

    deltas = []
    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.complete(
        model="stream-model",
        messages=[{"role": "user", "content": "Hello"}],
        on_text_delta=lambda value: _append_delta(deltas, value),
    )
    assert result["content"] == "Hello world."
    assert result["reasoning_details"] == [{"type": "opaque", "id": "r1"}]
    assert result["usage"]["total_tokens"] == 10
    assert "".join(deltas) == "Hello world."


async def _append_delta(deltas: list[str], value: str) -> None:
    deltas.append(value)


def test_model_router_uses_configured_model_assignments(monkeypatch):
    monkeypatch.setattr(settings, "primary_model", "primary-test")
    monkeypatch.setattr(settings, "coding_model", "coding-test")
    assert resolve_model("general") == "primary-test"
    assert resolve_model("coding") == "coding-test"
