from __future__ import annotations

DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_MODEL_LABEL = "GPT-5.5"
DEFAULT_CODEX_REASONING_EFFORT = "medium"
DEFAULT_CODEX_REASONING_EFFORTS = ["low", "medium", "high", "xhigh"]
DEFAULT_CODEX_SERVICE_TIER = "auto"
DEFAULT_CODEX_SERVICE_TIERS = ["auto", "fast"]


def fixed_codex_model(_: str | None = None) -> str:
    return DEFAULT_CODEX_MODEL
