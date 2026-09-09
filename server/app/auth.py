import time
from dataclasses import dataclass, field

from fastapi import Header, HTTPException, status

from .config import get_settings


@dataclass
class Principal:
    key: str
    owner: str


async def require_key(authorization: str | None = Header(default=None)) -> Principal:
    cfg = get_settings()
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        if cfg.allow_anonymous:
            return Principal(key="anonymous", owner="anonymous")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    owner = cfg.key_map.get(token)
    if owner is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown API key")
    return Principal(key=token, owner=owner)


@dataclass
class _Bucket:
    capacity: float
    tokens: float
    refill_per_s: float
    updated: float = field(default_factory=time.monotonic)

    def take(self, amount: float) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_s)
        self.updated = now
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True


class RateLimiter:
    """Two buckets per key: one for requests, one for tokens.

    In-process only. Behind more than one worker, back this with Redis and
    keep the same interface.
    """

    def __init__(self, rpm: int, tpm: int) -> None:
        self.rpm, self.tpm = rpm, tpm
        self._req: dict[str, _Bucket] = {}
        self._tok: dict[str, _Bucket] = {}

    def check_request(self, key: str) -> None:
        bucket = self._req.setdefault(key, _Bucket(self.rpm, self.rpm, self.rpm / 60))
        if not bucket.take(1):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"rate limit: {self.rpm} requests/min",
                headers={"retry-after": "5"},
            )

    def reserve_tokens(self, key: str, estimate: int) -> None:
        bucket = self._tok.setdefault(key, _Bucket(self.tpm, self.tpm, self.tpm / 60))
        if not bucket.take(estimate):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"rate limit: {self.tpm} tokens/min",
                headers={"retry-after": "10"},
            )

    def refund_tokens(self, key: str, amount: int) -> None:
        """Give back the unused part of a reservation once the stream ends."""
        if bucket := self._tok.get(key):
            bucket.tokens = min(bucket.capacity, bucket.tokens + max(0, amount))


limiter = RateLimiter(get_settings().rpm_limit, get_settings().tpm_limit)
