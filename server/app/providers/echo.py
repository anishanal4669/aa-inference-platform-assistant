import asyncio
import random
from collections.abc import AsyncIterator

from ..schemas import ModelSpec, StreamRequest, TextDelta, UpstreamUsage

FILLER = (
    "Streaming works the same way regardless of what sits behind this gateway. "
    "The server opens one HTTP response, holds it, and writes a frame every time "
    "the model produces text. Nothing is buffered on your behalf, so the number "
    "you should watch is time to first token rather than total latency. "
    "Swap this tier onto a real backend by changing its provider in the catalog."
)


class EchoProvider:
    """Deterministic local backend for development and CI.

    Emits tokens at a believable rate so the frontend's metering, cancellation
    and heartbeat paths can be exercised without a model server.
    """

    async def stream(self, req: StreamRequest, spec: ModelSpec) -> AsyncIterator:
        prompt = (req.messages or [])[-1].content if req.messages else ""
        body = f'You said: "{prompt.strip()[:160]}"\n\n{FILLER}'
        words = body.split(" ")

        rng = random.Random(len(prompt))
        await asyncio.sleep(0.12 + rng.random() * 0.18)  # simulated queue + prefill

        emitted = 0
        for i, word in enumerate(words):
            if emitted >= req.max_tokens:
                break
            yield TextDelta(word if i == 0 else " " + word)
            emitted += 1
            await asyncio.sleep(0.018 + rng.random() * 0.014)

        yield UpstreamUsage(input_tokens=max(1, len(prompt) // 4), output_tokens=emitted)
