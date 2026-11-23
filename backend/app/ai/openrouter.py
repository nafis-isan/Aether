import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import settings


class OpenRouterError(Exception):
    def __init__(self, code: str, user_message: str, *, retryable: bool = False):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable


class OpenRouterClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._sleep = sleep

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if not settings.openrouter_api_key:
            raise OpenRouterError("configuration_error", "The AI provider is not configured.")

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "reasoning": {"enabled": True},
            "max_tokens": settings.agent_max_completion_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if on_text_delta is not None and response_format is None:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        retries = max(0, settings.openrouter_max_retries)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.openrouter_timeout_seconds),
            transport=self._transport,
        ) as client:
            if on_text_delta is not None and response_format is None:
                return await self._complete_streaming(
                    client=client,
                    url=url,
                    headers=headers,
                    payload=payload,
                    model=model,
                    retries=retries,
                    on_text_delta=on_text_delta,
                )
            for attempt in range(retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.TimeoutException:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("timeout", "The AI provider took too long to respond.") from None
                except httpx.RequestError:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.") from None

                if response.status_code == 401:
                    raise OpenRouterError("invalid_api_key", "The AI provider rejected its server-side credentials.")
                if response.status_code == 404:
                    raise OpenRouterError("model_unavailable", "The configured AI model is unavailable.")
                if response.status_code == 429:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("rate_limited", "The AI provider is rate limiting requests.")
                if response.status_code >= 500:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")
                if response.is_error:
                    raise OpenRouterError("provider_error", "The AI provider could not process this request.")

                try:
                    body = response.json()
                    message = body["choices"][0]["message"]
                    content = message.get("content")
                    tool_calls = message.get("tool_calls", [])
                    if not isinstance(tool_calls, list):
                        raise ValueError("Tool calls must be a list")
                    if not (isinstance(content, str) and content.strip()) and not tool_calls:
                        raise ValueError("Assistant response content is missing")
                except (ValueError, KeyError, IndexError, TypeError):
                    raise OpenRouterError("invalid_response", "The AI provider returned an invalid response.") from None

                usage = body.get("usage")
                return {
                    "content": content,
                    "reasoning_details": message.get("reasoning_details"),
                    "tool_calls": tool_calls,
                    "model": body.get("model", model),
                    "usage": usage if isinstance(usage, dict) else None,
                }

        raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")

    async def _complete_streaming(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        model: str,
        retries: int,
        on_text_delta: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any]:
        for attempt in range(retries + 1):
            emitted_text = False
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code == 401:
                        raise OpenRouterError(
                            "invalid_api_key",
                            "The AI provider rejected its server-side credentials.",
                        )
                    if response.status_code == 404:
                        raise OpenRouterError("model_unavailable", "The configured AI model is unavailable.")
                    if response.status_code == 429:
                        if attempt < retries:
                            await self._backoff(attempt)
                            continue
                        raise OpenRouterError("rate_limited", "The AI provider is rate limiting requests.")
                    if response.status_code >= 500:
                        if attempt < retries:
                            await self._backoff(attempt)
                            continue
                        raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")
                    if response.is_error:
                        raise OpenRouterError("provider_error", "The AI provider could not process this request.")

                    if "text/event-stream" not in response.headers.get("content-type", "").lower():
                        await response.aread()
                        try:
                            parsed = response.json()
                            message = parsed["choices"][0]["message"]
                            if not isinstance(message, dict):
                                raise ValueError("Assistant message must be an object")
                            content = message.get("content")
                            tool_calls = message.get("tool_calls", [])
                            if not isinstance(tool_calls, list):
                                raise ValueError("Tool calls must be a list")
                            if not (isinstance(content, str) and content.strip()) and not tool_calls:
                                raise ValueError("Assistant response content is missing")
                        except (ValueError, KeyError, IndexError, TypeError):
                            raise OpenRouterError(
                                "invalid_response",
                                "The AI provider returned an invalid response.",
                            ) from None
                        if isinstance(content, str) and content:
                            await on_text_delta(content)
                        return {
                            "content": content,
                            "reasoning_details": message.get("reasoning_details"),
                            "tool_calls": tool_calls,
                            "model": parsed.get("model", model),
                            "usage": parsed.get("usage") if isinstance(parsed.get("usage"), dict) else None,
                        }

                    content_parts: list[str] = []
                    tool_call_deltas: dict[int, dict[str, Any]] = {}
                    reasoning_parts: list[Any] = []
                    usage: dict[str, Any] | None = None
                    response_model = model
                    pending_text: list[str] = []
                    last_text_delivery = time.monotonic()

                    async def deliver_text(text: str = "", *, flush: bool = False) -> None:
                        nonlocal last_text_delivery
                        if text:
                            pending_text.append(text)
                        buffered = "".join(pending_text)
                        if buffered and (
                            flush or len(buffered) >= 64 or time.monotonic() - last_text_delivery >= 0.1
                        ):
                            pending_text.clear()
                            last_text_delivery = time.monotonic()
                            await on_text_delta(buffered)

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            raise OpenRouterError(
                                "invalid_response",
                                "The AI provider returned an invalid stream.",
                            ) from None
                        if not isinstance(chunk, dict):
                            continue
                        chunk_model = chunk.get("model")
                        if isinstance(chunk_model, str):
                            response_model = chunk_model
                        chunk_usage = chunk.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage
                        choices = chunk.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        if not isinstance(choices[0], dict):
                            raise OpenRouterError(
                                "invalid_response",
                                "The AI provider returned an invalid stream.",
                            )
                        delta = choices[0].get("delta", {})
                        if not isinstance(delta, dict):
                            continue
                        reasoning_details = delta.get("reasoning_details", chunk.get("reasoning_details"))
                        if isinstance(reasoning_details, list):
                            reasoning_parts.extend(reasoning_details)
                        elif reasoning_details is not None:
                            reasoning_parts.append(reasoning_details)
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            content_parts.append(text)
                            emitted_text = True
                            await deliver_text(text)
                        tool_deltas = delta.get("tool_calls", [])
                        if not isinstance(tool_deltas, list):
                            raise OpenRouterError(
                                "invalid_response",
                                "The AI provider returned an invalid tool stream.",
                            )
                        for item in tool_deltas:
                            if not isinstance(item, dict):
                                continue
                            index = item.get("index")
                            if not isinstance(index, int) or isinstance(index, bool):
                                continue
                            aggregate = tool_call_deltas.setdefault(
                                index,
                                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                            )
                            if isinstance(item.get("id"), str):
                                aggregate["id"] += item["id"]
                            function = item.get("function")
                            if isinstance(function, dict):
                                if isinstance(function.get("name"), str):
                                    aggregate["function"]["name"] += function["name"]
                                if isinstance(function.get("arguments"), str):
                                    aggregate["function"]["arguments"] += function["arguments"]

                    await deliver_text(flush=True)
                    content = "".join(content_parts) or None
                    tool_calls = [tool_call_deltas[index] for index in sorted(tool_call_deltas)]
                    if not (isinstance(content, str) and content.strip()) and not tool_calls:
                        raise OpenRouterError(
                            "invalid_response",
                            "The AI provider returned an invalid response.",
                        )
                    return {
                        "content": content,
                        "reasoning_details": reasoning_parts or None,
                        "tool_calls": tool_calls,
                        "model": response_model,
                        "usage": usage,
                    }
            except OpenRouterError:
                raise
            except httpx.TimeoutException:
                if attempt < retries and not emitted_text:
                    await self._backoff(attempt)
                    continue
                raise OpenRouterError("timeout", "The AI provider took too long to respond.") from None
            except httpx.RequestError:
                if attempt < retries and not emitted_text:
                    await self._backoff(attempt)
                    continue
                raise OpenRouterError(
                    "provider_unavailable",
                    "The AI provider is temporarily unavailable.",
                ) from None
        raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(min(2**attempt + random.random(), 5.0))
