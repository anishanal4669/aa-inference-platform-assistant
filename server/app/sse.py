import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from .schemas import Heartbeat

SSE_HEADERS = {
    "cache-control": "no-cache, no-transform",
    "connection": "keep-alive",
    # nginx buffers event streams by default and ruins time-to-first-token.
    "x-accel-buffering": "no",
}


def event(name: str, data: Any) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {name}\ndata: {payload}\n\n"


def comment(text: str = "ping") -> str:
    return f": {text}\n\n"


async def with_heartbeat(source: AsyncIterator, interval: float) -> AsyncIterator:
    """Yield Heartbeat() during quiet periods without disturbing the upstream read.

    asyncio.wait_for would cancel an in-flight __anext__ on timeout and corrupt
    the HTTP stream, so the pending read is held across timeouts instead.
    """
    it = source.__aiter__()
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield Heartbeat()
                continue
            task, pending = pending, None
            try:
                item = task.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        if pending is not None:
            pending.cancel()
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()
