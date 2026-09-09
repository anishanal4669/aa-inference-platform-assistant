from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from env vars prefixed with GATEWAY_ (or a .env file)."""

    # --- auth ---
    # "sk-demo:demo-user,sk-alice:alice" -> key: owner
    api_keys: str = "sk-demo:demo-user"
    allow_anonymous: bool = True  # turn OFF in production

    # --- limits (per key, sliding window) ---
    rpm_limit: int = 30
    tpm_limit: int = 60_000
    request_timeout_s: float = 120.0
    heartbeat_s: float = 15.0

    # --- upstreams ---
    # Any OpenAI-compatible server: vLLM, TGI, Ollama, llama.cpp, TogetherAI...
    openai_base_url: str = "http://localhost:8000/v1"
    openai_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: str = ""

    # --- catalog ---
    models_file: str | None = None  # JSON overriding the built-in tiers

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    @property
    def key_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            key, _, owner = pair.partition(":")
            out[key.strip()] = owner.strip() or "anonymous"
        return out

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
