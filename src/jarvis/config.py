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


COMPUTER_BACKENDS = ("auto", "windows", "x11", "fake")
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
class ComputerSettings:
    """Computer control (mouse, keyboard, screen, windows, applications). Opt-in; every action is permission-checked."""
    enabled: bool = False              # off by default: moving the mouse / typing is a serious capability
    backend: str = "auto"              # auto (windows on Windows, x11 elsewhere) | windows | x11 | fake
    default_monitor: int = 0           # monitor index; 0 = primary
    screenshot_max_items: int = 3      # screenshots kept in memory (never written to disk unless explicitly saved)
    screenshot_max_pixels: int = 33_177_600  # refuse to capture more than this (8K)
    max_text_length: int = 500         # characters per typing action
    type_interval: float = 0.02        # seconds between typed characters
    max_scroll: int = 20               # scroll clicks per action
    max_hotkey_keys: int = 4
    action_delay: float = 0.05         # settle time after each action (seconds)
    max_actions_per_minute: int = 120  # runaway protection (0 = unlimited)
    show_text_preview: bool = True     # show the first characters of text to be typed in the confirmation prompt
    confirm_keyboard_each_time: bool = True      # keyboard actions are always asked, never covered by a session grant
    confirm_window_close_each_time: bool = True  # closing a window is always asked
    apps: dict[str, str] = field(default_factory=dict)  # application aliases -> executable path (TOML table)
    use_default_apps: bool = True      # add Notepad/Calculator/Paint aliases on Windows
    allow_unlisted_apps: bool = False  # True: absolute .exe paths may be launched too (still confirmed, still filtered)
    blocked_processes: tuple[str, ...] = ("explorer.exe",)  # input/close refused for these (adds to the built-in list)
    blocked_titles: tuple[str, ...] = ()                     # window-title fragments to refuse (adds to the built-in list)


@dataclass(frozen=True)
class AgentsSettings:
    """Multi-agent orchestration (v1). It only coordinates agents; every action of an agent still goes through ToolRegistry + PermissionEngine."""
    enabled: bool = False
    max_concurrent: int = 3            # agents working at the same time; further tasks stay PENDING
    task_timeout_seconds: float = 300.0
    max_queue: int = 50                # tasks waiting for a free agent/slot; more are BLOCKED(queue_full)
    max_history: int = 200             # finished tasks kept for /agenttasks
    cancel_grace_seconds: float = 5.0  # an agent that ignores cancel/timeout this long is marked FAILED
    tool_call_limit: int = 200         # tool calls per task
    max_output_chars: int = 20_000     # size of a stored task output


CODING_PROVIDERS = ("local", "fake")
CODING_TEST_COMMANDS = ("pytest", "python -m pytest", "python -m unittest", "npm test")  # the only runners that exist


@dataclass(frozen=True)
class CodingSettings:
    """Coding agent (v1). Opt-in; every action is permission-checked; no shell, no network, no commit/push."""
    enabled: bool = False
    provider: str = "local"            # local | fake (tests)
    workspace_roots: tuple[str, ...] = ()  # directories a workspace may be opened in; () = the JARVIS workspace directory
    max_actions_per_session: int = 300  # hard stop against runaway loops (reads count too)
    max_actions_per_minute: int = 120
    max_output_bytes: int = 200_000    # per stream of a test run; more output ends the run
    max_file_size: int = 1_000_000     # larger files are neither read, searched nor written
    max_search_results: int = 100
    max_list_entries: int = 500
    test_timeout: float = 120.0        # seconds per test run
    test_commands: tuple[str, ...] = ("pytest", "python -m pytest", "python -m unittest")  # subset of the known runners
    llm_context_chars: int = 12_000    # most characters of project material the `plan` action may send to the LLM
    confirm_delete_each_time: bool = True   # deleting is always asked, never covered by a session grant
    confirm_llm_each_time: bool = True      # sending material to the LLM provider is always asked


BROWSER_PROVIDERS = ("playwright", "fake")
BROWSER_KINDS = ("chromium", "chrome", "msedge")


@dataclass(frozen=True)
class BrowserSettings:
    """Browser agent (v1). Opt-in; every action is permission-checked; no profile, cookie or password handling."""
    enabled: bool = False
    provider: str = "playwright"       # playwright | fake (tests)
    browser: str = "chromium"          # chromium | chrome | msedge (Edge is preinstalled on Windows)
    executable_path: str = ""          # optional explicit browser binary
    headless: bool = False             # False: you can watch what JARVIS does
    navigation_timeout: float = 15.0   # seconds per navigation
    action_timeout: float = 5.0        # seconds per click/fill/...
    max_pages: int = 5                 # open tabs per session (popups beyond this are closed)
    max_text_chars: int = 20_000       # visible text returned per read
    max_elements: int = 100            # interactive elements listed per read
    max_actions_per_minute: int = 60
    max_actions_per_session: int = 300  # hard stop against runaway loops; start a new session to continue
    max_download_bytes: int = 50_000_000
    trusted_hosts: tuple[str, ...] = ()           # navigation to these hosts is GREEN (no question)
    blocked_hosts: tuple[str, ...] = ()           # never visited (RED)
    private_hosts_allowed: tuple[str, ...] = ()   # exact internal hosts that may be visited (e.g. "127.0.0.1")
    confirm_fill_each_time: bool = True           # typing into a page is always asked, never covered by a session grant
    confirm_file_transfer_each_time: bool = True  # downloads and uploads are always asked


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
    computer: ComputerSettings = field(default_factory=ComputerSettings)
    browser: BrowserSettings = field(default_factory=BrowserSettings)
    coding: CodingSettings = field(default_factory=CodingSettings)
    agents: AgentsSettings = field(default_factory=AgentsSettings)

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
        c = self.computer
        if c.backend not in COMPUTER_BACKENDS:
            raise ConfigError(f"computer.backend must be one of {COMPUTER_BACKENDS}, got {c.backend!r}")
        if c.default_monitor < 0 or c.screenshot_max_items < 1 or c.screenshot_max_pixels < 1:
            raise ConfigError("computer.default_monitor must be >= 0; screenshot_max_items/screenshot_max_pixels >= 1")
        if not 1 <= c.max_text_length <= 5000 or c.max_scroll < 1 or not 2 <= c.max_hotkey_keys <= 6:
            raise ConfigError("computer.max_text_length must be 1..5000, max_scroll >= 1, max_hotkey_keys 2..6")
        if c.type_interval < 0 or c.action_delay < 0 or c.max_actions_per_minute < 0:
            raise ConfigError("computer.type_interval/action_delay/max_actions_per_minute must be >= 0")
        for alias, path in c.apps.items():
            if not alias.strip() or not path.strip() or not alias.replace("_", "").replace("-", "").isalnum():
                raise ConfigError(f"computer.apps: invalid entry {alias!r} (alias: letters/digits/_/-, path non-empty)")
        if any(not x.strip() for x in (*c.blocked_processes, *c.blocked_titles)):
            raise ConfigError("computer.blocked_processes/blocked_titles must not contain empty entries")
        b = self.browser
        if b.provider not in BROWSER_PROVIDERS or b.browser not in BROWSER_KINDS:
            raise ConfigError(f"browser.provider must be one of {BROWSER_PROVIDERS}, browser.browser one of {BROWSER_KINDS}")
        if b.navigation_timeout <= 0 or b.action_timeout <= 0 or b.navigation_timeout > 300 or b.action_timeout > 120:
            raise ConfigError("browser.navigation_timeout must be 0..300 s and browser.action_timeout 0..120 s (positive)")
        if not 1 <= b.max_pages <= 20 or not 100 <= b.max_text_chars <= 500_000 or not 1 <= b.max_elements <= 1000:
            raise ConfigError("browser.max_pages 1..20, max_text_chars 100..500000, max_elements 1..1000")
        if b.max_actions_per_minute < 0 or b.max_actions_per_session < 0 or b.max_download_bytes < 1:
            raise ConfigError("browser.max_actions_per_minute/max_actions_per_session must be >= 0, max_download_bytes >= 1")
        if any(not x.strip() for x in (*b.trusted_hosts, *b.blocked_hosts, *b.private_hosts_allowed)):
            raise ConfigError("browser.trusted_hosts/blocked_hosts/private_hosts_allowed must not contain empty entries")
        if any(t.strip() in ("*", "*.*") or ("*" in t and not t.strip().startswith("*.")) for t in b.trusted_hosts):
            raise ConfigError("browser.trusted_hosts: use exact hosts or '*.example.com'; a bare wildcard is not allowed")
        if any("*" in h for h in b.private_hosts_allowed):
            raise ConfigError("browser.private_hosts_allowed takes exact hosts only (no wildcards)")
        cd = self.coding
        if cd.provider not in CODING_PROVIDERS:
            raise ConfigError(f"coding.provider must be one of {CODING_PROVIDERS}, got {cd.provider!r}")
        if any(c not in CODING_TEST_COMMANDS for c in cd.test_commands):
            raise ConfigError(f"coding.test_commands may only list known runners {CODING_TEST_COMMANDS}; arbitrary commands do not exist")
        if any(not r.strip() for r in cd.workspace_roots):
            raise ConfigError("coding.workspace_roots must not contain empty entries")
        if cd.max_actions_per_session < 0 or cd.max_actions_per_minute < 0:
            raise ConfigError("coding.max_actions_per_session/max_actions_per_minute must be >= 0")
        if not 1_000 <= cd.max_output_bytes <= 50_000_000 or not 100 <= cd.max_file_size <= 50_000_000:
            raise ConfigError("coding.max_output_bytes 1000..50000000, max_file_size 100..50000000")
        if not 1 <= cd.max_search_results <= 5000 or not 1 <= cd.max_list_entries <= 20000 or not 0 < cd.test_timeout <= 3600:
            raise ConfigError("coding.max_search_results 1..5000, max_list_entries 1..20000, test_timeout 0..3600 s")
        if not 500 <= cd.llm_context_chars <= 200_000:
            raise ConfigError("coding.llm_context_chars must be 500..200000")
        ag = self.agents
        if not 1 <= ag.max_concurrent <= 16 or not 0 < ag.task_timeout_seconds <= 3600 or not 1 <= ag.max_queue <= 1000:
            raise ConfigError("agents.max_concurrent 1..16, task_timeout_seconds 0..3600 (positive), max_queue 1..1000")
        if not 1 <= ag.max_history <= 10_000 or not 0 <= ag.cancel_grace_seconds <= 300 or not 1 <= ag.tool_call_limit <= 5000 \
                or not 1_000 <= ag.max_output_chars <= 1_000_000:
            raise ConfigError("agents.max_history 1..10000, cancel_grace_seconds 0..300, tool_call_limit 1..5000, max_output_chars 1000..1000000")
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
    if isinstance(template, dict):  # table-valued settings come from the TOML file only
        if not isinstance(value, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ConfigError(f"{name} must be a table of strings (set it in the TOML file)")
        return dict(value)
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
