"""Configuration: defaults < TOML file < environment variables (JARVIS_*)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from jarvis.errors import ConfigError

MODES = ("development", "production")


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "mock"
    model: str = "mock-1"
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: float = 60.0
    api_key: str | None = field(default=None, repr=False)  # never printed/logged
    base_url: str | None = None


@dataclass(frozen=True)
class Settings:
    mode: str = "development"
    log_level: str | None = None
    log_dir: str = "logs"
    workspace: str = "workspace"
    llm: LLMSettings = field(default_factory=LLMSettings)

    @property
    def is_production(self) -> bool:
        return self.mode == "production"

    @property
    def effective_log_level(self) -> str:
        return self.log_level or ("INFO" if self.is_production else "DEBUG")

    def validate(self) -> "Settings":
        if self.mode not in MODES:
            raise ConfigError(f"mode must be one of {MODES}, got {self.mode!r}")
        if not 0 <= self.llm.temperature <= 2:
            raise ConfigError("llm.temperature must be within [0, 2]")
        if self.llm.max_tokens <= 0:
            raise ConfigError("llm.max_tokens must be positive")
        if self.llm.timeout <= 0:
            raise ConfigError("llm.timeout must be positive")
        return self


def _coerce(value: Any, template: Any, name: str) -> Any:
    try:
        if isinstance(template, bool):
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
        if isinstance(template, int):
            return int(value)
        if isinstance(template, float):
            return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid value for {name}: {value!r}") from exc
    return value


def _apply(base: Any, data: Mapping[str, Any], prefix: str = "") -> Any:
    updates: dict[str, Any] = {}
    for key, value in data.items():
        if not hasattr(base, key):
            raise ConfigError(f"unknown config key: {prefix}{key}")
        current = getattr(base, key)
        if hasattr(current, "__dataclass_fields__"):
            if not isinstance(value, Mapping):
                raise ConfigError(f"{prefix}{key} must be a table")
            updates[key] = _apply(current, value, f"{prefix}{key}.")
        else:
            updates[key] = _coerce(value, current, prefix + key) if current is not None else value
    return replace(base, **updates)


def load_settings(path: str | Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings. `env` defaults to os.environ (injectable for tests)."""
    env = os.environ if env is None else env
    settings = Settings()

    if path is None and env.get("JARVIS_CONFIG"):
        path = env["JARVIS_CONFIG"]
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise ConfigError(f"config file not found: {p}")
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"cannot read config {p}: {exc}") from exc
        settings = _apply(settings, data)

    top = {"MODE": "mode", "LOG_LEVEL": "log_level", "LOG_DIR": "log_dir", "WORKSPACE": "workspace"}
    llm = {"PROVIDER": "provider", "MODEL": "model", "TEMPERATURE": "temperature",
           "MAX_TOKENS": "max_tokens", "TIMEOUT": "timeout", "BASE_URL": "base_url"}
    top_data = {v: env[f"JARVIS_{k}"] for k, v in top.items() if f"JARVIS_{k}" in env}
    llm_data = {v: env[f"JARVIS_LLM_{k}"] for k, v in llm.items() if f"JARVIS_LLM_{k}" in env}
    if top_data:
        settings = _apply(settings, top_data)
    if llm_data:
        settings = _apply(settings, {"llm": llm_data})

    # API keys: provider-specific env var, or generic JARVIS_LLM_API_KEY.
    key_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(settings.llm.provider)
    api_key = env.get("JARVIS_LLM_API_KEY") or (env.get(key_var) if key_var else None)
    if api_key:
        settings = replace(settings, llm=replace(settings.llm, api_key=api_key))
    return settings.validate()
