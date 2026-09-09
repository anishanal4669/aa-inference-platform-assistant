import json
from collections.abc import AsyncIterator

import httpx

from ..config import get_settings
from ..schemas import ModelSpec, StreamRequest, TextDelta, UpstreamUsage


class OpenAICompatProvider:
    """Works against anything speaking /chat/completions: vLLM, TGI, Ollama,
    llama.cpp server, or a hosted provider. Set GATEWAY_OPENAI_BASE_URL."""

    async def stream(self, req: StreamRequest, spec: ModelSpec) -> AsyncIterator:
        from . import UpstreamError  # local import avoids a cycle

        cfg = get_settings()
        payload = {
            "model": spec.upstream_model,
            "messages": [m.model_dump() for m in req.messages or []],
            "temperature": req.temperature,
            "max_tokens": min(req.max_tokens, spec.max_output_tokens),
            "stream": True,
            # vLLM and OpenAI both return a final usage frame with this set.
            "stream_options": {"include_usage": True},
        }
        if req.stop:
            payload["stop"] = req.stop

        headers = {"content-type": "application/json"}
        if cfg.openai_api_key:
            headers["authorization"] = f"Bearer {cfg.openai_api_key}"

        url = cfg.openai_base_url.rstrip("/") + "/chat/completions"
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
                        if not data or data == "[DONE]":
                            continue
                        try:
                            frame = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        for choice in frame.get("choices") or []:
                            text = (choice.get("delta") or {}).get("content")
                            if text:
                                yield TextDelta(text)
                        if usage := frame.get("usage"):
                            yield UpstreamUsage(
                                input_tokens=usage.get("prompt_tokens"),
                                output_tokens=usage.get("completion_tokens"),
                            )
            except httpx.HTTPError as exc:
                raise UpstreamError(f"cannot reach upstream: {exc}") from exc
