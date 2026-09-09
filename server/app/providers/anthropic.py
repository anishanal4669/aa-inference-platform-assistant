import json
from collections.abc import AsyncIterator

import httpx

from ..config import get_settings
from ..schemas import ModelSpec, StreamRequest, TextDelta, UpstreamUsage


class AnthropicProvider:
    """Anthropic Messages API. System messages move into the top-level field."""

    async def stream(self, req: StreamRequest, spec: ModelSpec) -> AsyncIterator:
        from . import UpstreamError

        cfg = get_settings()
        if not cfg.anthropic_api_key:
            raise UpstreamError("GATEWAY_ANTHROPIC_API_KEY is not set", 500)

        system = " ".join(m.content for m in (req.messages or []) if m.role == "system")
        turns = [m.model_dump() for m in (req.messages or []) if m.role != "system"]

        payload: dict = {
            "model": spec.upstream_model,
            "messages": turns,
            "max_tokens": min(req.max_tokens, spec.max_output_tokens),
            "temperature": min(req.temperature, 1.0),
            "stream": True,
        }
        if system:
            payload["system"] = system
        if req.stop:
            payload["stop_sequences"] = req.stop

        url = cfg.anthropic_base_url.rstrip("/") + "/v1/messages"
        headers = {
            "content-type": "application/json",
            "x-api-key": cfg.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        }
        timeout = httpx.Timeout(cfg.request_timeout_s, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as res:
                    if res.status_code >= 400:
                        body = (await res.aread()).decode()[:400]
                        raise UpstreamError(f"upstream {res.status_code}: {body}", res.status_code)
                    async for line in res.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            ev = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        kind = ev.get("type")
                        if kind == "content_block_delta":
                            text = (ev.get("delta") or {}).get("text")
                            if text:
                                yield TextDelta(text)
                        elif kind == "message_start":
                            usage = (ev.get("message") or {}).get("usage") or {}
                            if "input_tokens" in usage:
                                yield UpstreamUsage(input_tokens=usage["input_tokens"])
                        elif kind == "message_delta":
                            usage = ev.get("usage") or {}
                            if "output_tokens" in usage:
                                yield UpstreamUsage(output_tokens=usage["output_tokens"])
                        elif kind == "error":
                            msg = (ev.get("error") or {}).get("message", "upstream error")
                            raise UpstreamError(msg)
            except httpx.HTTPError as exc:
                raise UpstreamError(f"cannot reach upstream: {exc}") from exc
