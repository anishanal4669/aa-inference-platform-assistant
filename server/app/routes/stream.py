import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..auth import Principal, limiter, require_key
from ..metering import RequestMeter, estimate_tokens, ledger
from ..providers import UpstreamError, get_provider
from ..registry import load_registry
from ..schemas import Heartbeat, StreamRequest, TextDelta, UpstreamUsage
from ..sse import SSE_HEADERS, comment, event, with_heartbeat

log = logging.getLogger("gateway.stream")
router = APIRouter()


@router.post("/v1/stream")
async def stream(
    body: StreamRequest,
    request: Request,
    principal: Principal = Depends(require_key),
) -> StreamingResponse:
    cfg = request.app.state.settings
    spec = load_registry().get(body.model)
    if spec is None:
        raise HTTPException(404, f"unknown model {body.model!r}")

    prompt = "\n".join(m.content for m in body.messages or [])
    prompt_tokens = estimate_tokens(prompt)
    if prompt_tokens > spec.context_window:
        raise HTTPException(413, f"prompt exceeds the {spec.context_window} token context window")

    limiter.check_request(principal.key)
    reservation = prompt_tokens + min(body.max_tokens, spec.max_output_tokens)
    limiter.reserve_tokens(principal.key, reservation)

    request_id = "req_" + uuid.uuid4().hex[:16]
    meter = RequestMeter(request_id=request_id, model=spec.id, owner=principal.owner)
    meter.input_tokens = prompt_tokens

    provider = get_provider(spec)
    source = provider.stream(body, spec)

    # Pull the first chunk here so an upstream failure becomes a real HTTP
    # status instead of a 200 with an error buried in the body.
    try:
        first = await source.__anext__()
    except StopAsyncIteration:
        first = None
    except UpstreamError as exc:
        await _aclose(source)
        raise HTTPException(exc.status, str(exc)) from exc

    async def body_iter() -> AsyncIterator[str]:
        yield event("start", {"request_id": request_id, "model": spec.id})
        try:
            if first is not None:
                async for frame in _render(first, meter):
                    yield frame
            async for chunk in with_heartbeat(source, cfg.heartbeat_s):
                if isinstance(chunk, Heartbeat):
                    yield comment()
                    continue
                async for frame in _render(chunk, meter):
                    yield frame
            meter.finish("stop")
            yield event("usage", meter.summary(spec))
            yield event("done", {"request_id": request_id})
        except UpstreamError as exc:
            meter.finish("error")
            log.warning("%s upstream error: %s", request_id, exc)
            yield event("error", {"type": "upstream_error", "message": str(exc)})
        except asyncio.CancelledError:
            # Client hung up. Bill what was produced, then let it propagate so
            # the upstream connection is torn down too.
            meter.finish("cancelled")
            raise
        finally:
            # Starlette usually closes the generator (GeneratorExit) rather than
            # cancelling it, so the disconnect is caught here instead.
            if meter.duration_ms == 0.0:
                meter.finish("cancelled")
            unused = max(0, reservation - meter.input_tokens - meter.output_tokens)
            limiter.refund_tokens(principal.key, unused)
            ledger.record(principal.owner, meter.summary(spec))
            log.info(
                "%s model=%s ttft=%sms out=%s tps=%s cost=$%s %s",
                request_id, spec.id, meter.summary(spec)["ttft_ms"], meter.output_tokens,
                meter.tokens_per_second, meter.cost_usd(spec), meter.finish_reason,
            )

    return StreamingResponse(
        body_iter(),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, "x-request-id": request_id},
    )


async def _render(chunk, meter: RequestMeter) -> AsyncIterator[str]:
    if isinstance(chunk, TextDelta):
        meter.on_text(chunk.text)
        yield event("delta", {"text": chunk.text})
    elif isinstance(chunk, UpstreamUsage):
        meter.on_upstream_usage(chunk.input_tokens, chunk.output_tokens)


async def _aclose(source) -> None:
    aclose = getattr(source, "aclose", None)
    if aclose is not None:
        await aclose()
