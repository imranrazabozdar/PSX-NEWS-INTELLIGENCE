"""Application settings, read only from PSXNI_-prefixed environment variables.

Phase 0: no database or external service is configured. Settings are only read here,
so secrets never end up hard-coded elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ENV_PREFIX = "PSXNI_"


def _get(name: str, default: str | None = None) -> str | None:
    return os.environ.get(ENV_PREFIX + name, default)


def _get_bool(name: str, default: bool = False) -> bool:
    value = _get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str
    kill_switch: bool
    database_configured: bool


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        pass
    return Settings(
        env=_get("ENV", "local") or "local",
        kill_switch=_get_bool("KILL_SWITCH", False),
        database_configured=bool(_get("TURSO_DATABASE_URL")),
    )
