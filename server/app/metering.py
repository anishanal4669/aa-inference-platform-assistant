import time
from collections import deque
from dataclasses import asdict, dataclass, field

from .schemas import ModelSpec


def estimate_tokens(text: str) -> int:
    """Cheap heuristic used only until the upstream reports real counts.

    Swap in tiktoken or the served model's tokenizer if you bill on this.
    """
    return max(1, round(len(text) / 4))


@dataclass
class RequestMeter:
    request_id: str
    model: str
    owner: str
    input_tokens: int = 0
    output_tokens: int = 0
    _output_chars: int = 0
    _upstream_output: int | None = None
    started: float = field(default_factory=time.perf_counter)
    ttft_ms: float | None = None
    duration_ms: float = 0.0
    finish_reason: str = "stop"

    def on_text(self, text: str) -> None:
        if self.ttft_ms is None:
            self.ttft_ms = (time.perf_counter() - self.started) * 1000
        self._output_chars += len(text)
        if self._upstream_output is None:
            self.output_tokens = estimate_tokens_from_chars(self._output_chars)

    def on_upstream_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self._upstream_output = output_tokens
            self.output_tokens = output_tokens

    def finish(self, reason: str = "stop") -> None:
        self.finish_reason = reason
        self.duration_ms = (time.perf_counter() - self.started) * 1000

    @property
    def tokens_per_second(self) -> float:
        if not self.ttft_ms or self.output_tokens <= 1:
            return 0.0
        decode_s = (self.duration_ms - self.ttft_ms) / 1000
        return round((self.output_tokens - 1) / decode_s, 2) if decode_s > 0 else 0.0

    def cost_usd(self, spec: ModelSpec) -> float:
        cost = (
            self.input_tokens / 1e6 * spec.input_price_per_mtok
            + self.output_tokens / 1e6 * spec.output_price_per_mtok
        )
        return round(cost, 6)

    def summary(self, spec: ModelSpec) -> dict:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "ttft_ms": round(self.ttft_ms, 1) if self.ttft_ms else None,
            "duration_ms": round(self.duration_ms, 1),
            "tokens_per_second": self.tokens_per_second,
            "cost_usd": self.cost_usd(spec),
            "finish_reason": self.finish_reason,
        }


def estimate_tokens_from_chars(chars: int) -> int:
    return max(1, round(chars / 4))


class UsageLedger:
    """Last N request summaries. Replace with your warehouse when billing."""

    def __init__(self, maxlen: int = 500) -> None:
        self._records: deque[dict] = deque(maxlen=maxlen)

    def record(self, owner: str, summary: dict) -> None:
        self._records.appendleft({"owner": owner, **summary})

    def recent(self, owner: str | None = None, limit: int = 50) -> list[dict]:
        rows = [r for r in self._records if owner is None or r["owner"] == owner]
        return rows[:limit]

    def totals(self, owner: str | None = None) -> dict:
        rows = self.recent(owner, limit=10_000)
        return {
            "requests": len(rows),
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        }


ledger = UsageLedger()

__all__ = ["RequestMeter", "UsageLedger", "ledger", "estimate_tokens", "asdict"]
