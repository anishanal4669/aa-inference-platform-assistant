from collections.abc import AsyncIterator
from typing import Protocol

from ..schemas import ModelSpec, StreamRequest, TextDelta, UpstreamUsage
from .anthropic import AnthropicProvider
from .echo import EchoProvider
from .openai_compat import OpenAICompatProvider

Chunk = TextDelta | UpstreamUsage


class Provider(Protocol):
    async def stream(
        self, req: StreamRequest, spec: ModelSpec
    ) -> AsyncIterator[Chunk]: ...


class UpstreamError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


_PROVIDERS: dict[str, Provider] = {
    "openai": OpenAICompatProvider(),
    "anthropic": AnthropicProvider(),
    "echo": EchoProvider(),
}


def get_provider(spec: ModelSpec) -> Provider:
    try:
        return _PROVIDERS[spec.provider]
    except KeyError:  # pragma: no cover - guarded by schema Literal
        raise UpstreamError(f"no provider registered for {spec.provider!r}", 500)


__all__ = ["Provider", "Chunk", "UpstreamError", "get_provider"]
