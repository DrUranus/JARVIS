"""Configuration: defaults < TOML file < environment variables (JARVIS_*)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
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
class VoiceSettings:
    """Voice interface. Defaults ('console') need no hardware and no API key."""
    stt_provider: str = "console"      # console | mock | openai
    tts_provider: str = "console"      # console | mock | system | openai
    audio_input: str = "sounddevice"   # microphone backend (used by non-console STT)
    audio_output: str = "system"       # playback backend (used by openai TTS)
    language: str = "de"
    wake_word: str = "jarvis"
    require_wake_word: bool = False
    speak_responses: bool = True
    sample_rate: int = 16000
    max_record_seconds: float = 15.0
    silence_seconds: float = 1.0
    silence_threshold: int = 500       # RMS of 16-bit samples below which audio counts as silence
    stt_model: str = "whisper-1"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    tts_command: str | None = None     # override for the 'system' TTS (e.g. "espeak-ng -v de")
    base_url: str | None = None
    timeout: float = 30.0
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class MemorySettings:
    """Persistent long-term memory. Local only; nothing is sent anywhere by the memory module itself."""
    enabled: bool = True
    backend: str = "sqlite"            # sqlite | memory (non-persistent, mainly for tests)
    path: str = "data/memory.db"       # sqlite file; created on first write
    max_relevant: int = 5              # max memories retrieved per request (0 = no automatic retrieval)
    recent_limit: int = 10             # default size of "recent memories" listings
    max_content_length: int = 2000     # characters per entry
    max_entries: int = 10000           # 0 = unlimited
    use_in_prompts: bool = False       # privacy: relevant memories are sent to the LLM only if true


SECURITY_MODES = ("standard", "lockdown")
CONFIRMATION_PROVIDERS = ("cli", "deny")


@dataclass(frozen=True)
class SecuritySettings:
    """Permissions & security. Defaults are restrictive and need no manual configuration."""
    mode: str = "standard"             # standard: GREEN auto, YELLOW asks | lockdown: only GREEN, nothing else
    confirmation: str = "cli"          # cli: ask the user in the terminal | deny: never ask (headless; YELLOW denied)
    policy_file: str | None = None     # optional TOML with explicit allow/confirm/deny rules
    allowed_roots: tuple[str, ...] = ()  # filesystem roots tools may touch; () = only the workspace directory
    denied_paths: tuple[str, ...] = ()   # always blocked, even inside allowed roots
    allow_session_grants: bool = True  # may the user answer "allow for this session"?
    session_ttl_seconds: int = 3600
    audit_enabled: bool = True
    audit_path: str = ""               # "" = <log_dir>/audit.jsonl
    audit_strict: bool = True          # if the audit log cannot be written, non-GREEN actions are denied
    audit_green: bool = False          # also log automatically allowed GREEN actions (verbose)


@dataclass(frozen=True)
class Settings:
    mode: str = "development"
    log_level: str | None = None
    log_dir: str = "logs"
    workspace: str = "workspace"
    llm: LLMSettings = field(default_factory=LLMSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)

    @property
    def is_production(self) -> bool:
        return self.mode == "production"

    @property
    def effective_fs_roots(self) -> tuple[str, ...]:
        """Filesystem roots tools may use: the configured ones, else only the workspace directory."""
        return self.security.allowed_roots or (self.workspace,)

    @property
    def effective_audit_path(self) -> str:
        return self.security.audit_path or str(Path(self.log_dir) / "audit.jsonl")

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
        v = self.voice
        if min(v.sample_rate, v.max_record_seconds, v.silence_seconds, v.timeout) <= 0:
            raise ConfigError("voice.sample_rate/max_record_seconds/silence_seconds/timeout must be positive")
        if v.silence_threshold < 0:
            raise ConfigError("voice.silence_threshold must be >= 0")
        if not v.wake_word.strip():
            raise ConfigError("voice.wake_word must not be empty")
        sec = self.security
        if sec.mode not in SECURITY_MODES:
            raise ConfigError(f"security.mode must be one of {SECURITY_MODES}, got {sec.mode!r}")
        if sec.confirmation not in CONFIRMATION_PROVIDERS:
            raise ConfigError(f"security.confirmation must be one of {CONFIRMATION_PROVIDERS}, got {sec.confirmation!r}")
        if sec.session_ttl_seconds <= 0:
            raise ConfigError("security.session_ttl_seconds must be positive")
        if any(not r.strip() for r in (*sec.allowed_roots, *sec.denied_paths)):
            raise ConfigError("security.allowed_roots/denied_paths must not contain empty entries")
        m = self.memory
        if not m.backend.strip():
            raise ConfigError("memory.backend must not be empty")
        if m.backend.lower() == "sqlite" and not m.path.strip():
            raise ConfigError("memory.path must not be empty for the sqlite backend")
        if m.max_relevant < 0 or m.max_entries < 0:
            raise ConfigError("memory.max_relevant/max_entries must be >= 0")
        if m.recent_limit <= 0 or m.max_content_length <= 0:
            raise ConfigError("memory.recent_limit/max_content_length must be positive")
        return self


def _coerce(value: Any, template: Any, name: str) -> Any:
    if isinstance(template, tuple):  # list-valued settings: TOML list, or an os.pathsep-separated env string
        if isinstance(value, str):
            return tuple(p.strip() for p in value.split(os.pathsep) if p.strip())
        if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
            return tuple(value)
        raise ConfigError(f"{name} must be a list of strings")
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


def _apply_env(settings: Settings, env: Mapping[str, str]) -> Settings:
    """JARVIS_<FIELD> for top-level fields, JARVIS_<SECTION>_<FIELD> for nested sections."""
    data: dict[str, Any] = {}
    for f in fields(settings):
        value = getattr(settings, f.name)
        if is_dataclass(value):
            section = {sf.name: env[f"JARVIS_{f.name}_{sf.name}".upper()]
                       for sf in fields(value) if f"JARVIS_{f.name}_{sf.name}".upper() in env}
            if section:
                data[f.name] = section
        elif f"JARVIS_{f.name}".upper() in env:
            data[f.name] = env[f"JARVIS_{f.name}".upper()]
    return _apply(settings, data) if data else settings


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

    settings = _apply_env(settings, env)

    # API keys: provider-specific env var unless an explicit JARVIS_*_API_KEY was given.
    llm_key_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(settings.llm.provider)
    if settings.llm.api_key is None and llm_key_var and env.get(llm_key_var):
        settings = replace(settings, llm=replace(settings.llm, api_key=env[llm_key_var]))
    if settings.voice.api_key is None and env.get("OPENAI_API_KEY") and "openai" in (
            settings.voice.stt_provider, settings.voice.tts_provider):
        settings = replace(settings, voice=replace(settings.voice, api_key=env["OPENAI_API_KEY"]))
    return settings.validate()
