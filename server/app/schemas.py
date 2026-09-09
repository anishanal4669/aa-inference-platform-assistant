from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class StreamRequest(BaseModel):
    model: str
    input: str | None = None
    messages: list[Message] | None = None
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(512, ge=1, le=32_000)
    stop: list[str] | None = None

    @model_validator(mode="after")
    def _need_one(self) -> "StreamRequest":
        if not self.input and not self.messages:
            raise ValueError("provide either `input` or `messages`")
        if self.input and not self.messages:
            self.messages = [Message(role="user", content=self.input)]
        return self


# ---- internal chunk types yielded by providers ----------------------------


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class UpstreamUsage:
    """Authoritative token counts, when the upstream reports them."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(slots=True)
class Heartbeat:
    """Emitted as an SSE comment so idle proxies don't drop the connection."""


class ModelSpec(BaseModel):
    id: str
    provider: Literal["openai", "anthropic", "echo"]
    upstream_model: str
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0
    max_output_tokens: int = 4096
    context_window: int = 32_768
    description: str = ""
