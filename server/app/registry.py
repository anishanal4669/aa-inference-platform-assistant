import json
from pathlib import Path

from .config import get_settings
from .schemas import ModelSpec

# Tier names are yours; upstream_model is what the backend actually serves.
DEFAULT_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="swift-8b",
        provider="echo",
        upstream_model="mistralai/Mistral-7B-Instruct-v0.3",
        input_price_per_mtok=0.15,
        output_price_per_mtok=0.60,
        max_output_tokens=4096,
        context_window=32_768,
        description="Small, fast, cheap. Good for classification and short replies.",
    ),
    ModelSpec(
        id="core-70b",
        provider="echo",
        upstream_model="meta-llama/Llama-3.3-70B-Instruct",
        input_price_per_mtok=0.55,
        output_price_per_mtok=2.20,
        max_output_tokens=8192,
        context_window=131_072,
        description="The default. Balanced quality and throughput.",
    ),
    ModelSpec(
        id="dense-400b",
        provider="echo",
        upstream_model="claude-sonnet-4-6",
        input_price_per_mtok=3.00,
        output_price_per_mtok=15.00,
        max_output_tokens=8192,
        context_window=200_000,
        description="Frontier tier for reasoning-heavy work.",
    ),
]


class Registry:
    def __init__(self, specs: list[ModelSpec]) -> None:
        self._by_id = {s.id: s for s in specs}

    def list(self) -> list[ModelSpec]:
        return list(self._by_id.values())

    def get(self, model_id: str) -> ModelSpec | None:
        return self._by_id.get(model_id)


def load_registry() -> Registry:
    """Built-in catalog, unless GATEWAY_MODELS_FILE points at a JSON array."""
    path = get_settings().models_file
    if not path:
        return Registry(DEFAULT_MODELS)
    raw = json.loads(Path(path).read_text())
    return Registry([ModelSpec.model_validate(item) for item in raw])
