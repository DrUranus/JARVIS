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
    allow_remote: bool = False         # openai_compatible only: a non-loopback base_url is refused unless true


@dataclass(frozen=True)
class VoiceSettings:
    """Voice interface. Defaults ('console') need no hardware and no API key."""
    stt_provider: str = "console"      # console | mock | openai | local
    tts_provider: str = "console"      # console | mock | system | openai
    audio_input: str = "sounddevice"   # microphone backend (used by non-console STT)
    audio_output: str = "system"       # playback backend (used by openai TTS)
    hotword_detector: str = "none"     # none | mock | <registered local detector>; gates the microphone, no engine ships by default
    language: str = "de"
    wake_word: str = "jarvis"
    require_wake_word: bool = False
    speak_responses: bool = True
    sample_rate: int = 16000
    max_record_seconds: float = 15.0
    silence_seconds: float = 1.0
    silence_threshold: int = 500       # RMS of 16-bit samples below which audio counts as silence
    vad_provider: str = "none"         # none (bisheriger Pegel-Endpointer) | energy | silero (Extra 'stt-local'); Aufnahme endet nach Sprechpause, hoechstens max_record_seconds
    vad_min_speech_seconds: float = 0.2  # vad_provider != none: Sprache zaehlt erst nach dieser Dauer am Stueck (Klicks nicht)
    stt_model: str = "whisper-1"
    stt_model_dir: str | None = None   # stt_provider "local": lokales Modellverzeichnis (kein Download; Extra 'stt-local')
    stt_device: str = "cpu"            # stt_provider "local": cpu | cuda
    stt_compute_type: str = "int8"     # stt_provider "local": CTranslate2-Rechengenauigkeit
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
    backend: str = "sqlite"            # sqlite | semantic (sqlite + local TF-IDF search) | memory | semantic-memory (non-persistent)
    path: str = "data/memory.db"       # sqlite file; created on first write
    max_relevant: int = 5              # max memories retrieved per request (0 = no automatic retrieval)
    recent_limit: int = 10             # default size of "recent memories" listings
    max_content_length: int = 2000     # characters per entry
    max_entries: int = 10000           # 0 = unlimited
    use_in_prompts: bool = False       # privacy: relevant memories are sent to the LLM only if true


@dataclass(frozen=True)
class HistorySettings:
    """Persistent history of FINISHED goals, agent tasks, repair runs and plans (status, short text, times, failure reason; secrets redacted). Opt-in, local only.
    It is display only: after a restart nothing is resumed or started."""
    enabled: bool = False
    path: str = "data/history.db"      # sqlite file; created on first write
    max_entries: int = 500             # oldest entries are dropped first (hard limit 100000)
    max_text_length: int = 300         # characters per text field


@dataclass(frozen=True)
class JournalSettings:
    """Persistent task journal: goals, agent tasks and their steps (status, times, step number, side_effect flag, redacted short text, result summary
    with evidence). Opt-in, local only. Storing and reading only: after a restart nothing is resumed or started."""
    enabled: bool = False
    path: str = "data/journal.db"      # sqlite file; created on first write; a corrupt file is never overwritten
    max_entries: int = 500             # oldest entries are dropped first (hard limit 100000)
    max_steps_per_entry: int = 50      # steps kept per goal/task (hard limit 200)
    max_text_length: int = 300         # characters per text field
    max_evidence: int = 5              # evidence items per result (hard limit 20)


@dataclass(frozen=True)
class AssistantSettings:
    """End-to-end assistant wiring (assistant-e2e): connects the journal, the agent router and the UI-contract adapter to the existing layers. It adds no
    autonomy: nothing starts by itself, every action still runs ToolRegistry.execute -> PermissionEngine. OFF by default; needs agents.enabled."""
    enabled: bool = False
    confirmation_timeout_seconds: float = 120.0     # an unanswered question counts as DENIED after this time (1..600)


@dataclass(frozen=True)
class ControlCenterSettings:
    """Control Center (cc-backend-binding): allows the explicit start command `jarvis-cc` (local web UI on 127.0.0.1 only). OFF by default; it needs
    assistant.enabled (the real UiBackend). It starts nothing by itself and adds no permission path: commands still end in the engine."""
    enabled: bool = False


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
    uia_enabled: bool = False          # read-only Windows UI-Automation provider (extra "uia"); off by default, needs computer.enabled
    uia_max_calls_per_session: int = 200   # session budget of UI reads (1..10000); never reset by halt/resume
    uia_call_timeout: float = 20.0     # seconds before a hanging UIA worker is stopped (0..600)
    uia_actions_enabled: bool = False  # UIA actions by pattern (tool ui_act: invoke/set_value/select/toggle/focus); off by default, needs uia_enabled; each action is confirmed


@dataclass(frozen=True)
class AgentRouterSettings:
    """Agent router (agent-router): picks the suitable registered agent/capabilities for a task - rules first-class, an optional LLM proposal as a
    checked candidate. It executes nothing and grants nothing. OFF by default; not started by itself."""
    enabled: bool = False
    timeout_seconds: float = 5.0       # hard bound for the optional LLM proposal (0..60, positive); on expiry the rules decide
    max_objective_chars: int = 500     # objective text (redacted, cut) offered to the LLM (1..2000)
    max_reason_chars: int = 200        # length of the stored reason (1..300)


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
    router: AgentRouterSettings = field(default_factory=AgentRouterSettings)


@dataclass(frozen=True)
class GoalsSettings:
    """Goal engine (v1). Opt-in; needs the multi-agent layer. It plans and supervises steps; it adds no capability and no permission."""
    enabled: bool = False
    max_steps: int = 20                    # steps per goal (hard limit 50)
    max_attempts_per_step: int = 2         # 1 = no retry (hard limit 5)
    goal_timeout_seconds: float = 1800.0
    step_timeout_seconds: float = 300.0
    max_active_goals: int = 3
    max_history: int = 100                 # finished goals kept for /goals
    replanning: bool = False               # after a retryable failure ask the LLM provider for an alternative plan (at most 2 attempts per goal). OFF: it sends the goal text and redacted step results to the provider
    llm_planning: bool = False             # split NEW goals with the LLM provider; a candidate must pass the plan check, else the fixed templates are used. OFF: it sends the goal text and the template plan to the provider


ROUTING_TASKS = ("chat", "plan", "code", "research", "vision", "speech")


@dataclass(frozen=True)
class RoutingSettings:
    """LLM routing policy (docs/LLM_ROUTING.md). OFF by default: then `llm.provider` alone serves every request, exactly as before. Only read at startup."""
    enabled: bool = False
    local_provider: str = ""               # registered provider name used for local work (empty = none: nothing is routed locally)
    cloud_provider: str = ""               # registered provider name counted as cloud (empty = no cloud target at all)
    cloud_tasks: tuple[str, ...] = ()      # task classes that MAY use the cloud (empty = none; "speech" is never allowed)


@dataclass(frozen=True)
class LlmBudgetSettings:
    """LLM token / call / cost budget (E6). OFF by default: then the provider object is used exactly as before. Provisional development defaults of the owner; limits are
    frozen for the session and never raised automatically. Money values are TEXT decimals (no floats); a cost limit without a known price refuses the call (fail-closed)."""
    enabled: bool = False
    max_calls: int = 30                        # LLM calls per session (hard limit 100000)
    max_input_tokens_per_call: int = 50_000    # ESTIMATED input tokens of one call (characters / 3)
    max_output_tokens_per_call: int = 2048     # planned output tokens: request.max_tokens, else llm.max_tokens
    max_input_tokens_session: int = 50_000     # estimated or measured input tokens of the whole session
    max_tokens_session: int = 100_000          # input + output tokens of the whole session
    max_cost: str = ""                         # "" = no cost limit; otherwise a positive decimal text (currency-agnostic units)
    prices: tuple[str, ...] = ()               # "model;input_per_1k;output_per_1k" (text decimals). Unknown model = UNKNOWN price, never estimated

    def to_limits(self):
        from jarvis.llm.cost_budget import CostBudgetLimits
        for name in ("max_calls", "max_input_tokens_per_call", "max_output_tokens_per_call", "max_input_tokens_session", "max_tokens_session"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                raise ValueError(f"{name} must be a whole number")
        if not isinstance(self.max_cost, str):
            raise ValueError("max_cost must be a text decimal (no float)")
        return CostBudgetLimits(self.max_calls, self.max_input_tokens_per_call, self.max_output_tokens_per_call, self.max_tokens_session,
                                max_cost=self.max_cost.strip() or None, max_input_tokens_session=self.max_input_tokens_session)

    def to_prices(self):
        from jarvis.llm.cost_budget import ModelPrice, PriceTable, make_price
        out: dict[str, ModelPrice] = {}
        for entry in self.prices:
            parts = entry.split(";") if isinstance(entry, str) else []
            if len(parts) != 3 or not parts[0].strip():
                raise ValueError(f"price entry {entry!r} must be 'model;input_per_1k;output_per_1k'")
            model = parts[0].strip()
            if model in out:
                raise ValueError(f"price of {model!r} is listed twice")
            out[model] = make_price(parts[1].strip(), parts[2].strip())
        return PriceTable(out)


@dataclass(frozen=True)
class BudgetSettings:
    """Session budget (Phase 14): one cap on tool calls and run time for the whole process, across all goals and agents. Enforced by the permission engine."""
    enabled: bool = False
    max_tool_calls: int = 500              # all approved tool calls, GREEN included (hard limit 100000)
    max_runtime_seconds: float = 3600.0    # from the first approved action (hard limit 86400)


@dataclass(frozen=True)
class SelfRepairSettings:
    """Self-testing / self-repair (v1). Opt-in; needs the multi-agent layer and the coding agent; works only in an explicitly named workspace."""
    enabled: bool = False
    max_attempts: int = 3              # repair attempts per run (hard limit 5)
    repair_timeout_seconds: float = 900.0
    step_timeout_seconds: float = 300.0
    max_active_repairs: int = 1
    max_history: int = 50


@dataclass(frozen=True)
class SelfImprovementSettings:
    """Self-improvement (Phase 15) - a DISABLED PROPOSAL WORKFLOW. With enabled = true it only analyses recorded run data, stores proposals (HMAC-signed) and keeps
    their status; it never prepares, tests, imports, runs, merges or activates code. allow_prepare, allow_activation and repo_path exist as reserved keys: any
    value other than the default is rejected at startup because execution isolation has not been proven (see src/jarvis/self_improvement/isolation.py)."""
    enabled: bool = False
    use_llm: bool = False                  # the LLM provider may reword proposals (sends redacted observations to it)
    repo_path: str = ""                    # RESERVED - must stay empty
    data_dir: str = "data/improvements"    # must lie OUTSIDE security.allowed_roots and coding.workspace_roots (checked at startup, fail closed)
    key_path: str = ""                     # HMAC key file for proposals.json ("" = ~/.jarvis/self_improvement.store.key); outside data_dir and every allowed root
    allow_prepare: bool = False            # RESERVED - must stay false
    allow_activation: bool = False         # RESERVED - must stay false
    max_proposals: int = 200
    min_occurrences: int = 2               # a problem must be recorded this often before it becomes a proposal
    max_edits: int = 5                     # reserved for a later, isolated version
    max_diff_bytes: int = 100_000          # reserved
    prepare_timeout_seconds: float = 60.0  # reserved
    test_timeout_seconds: float = 600.0    # reserved
    regression_paths: tuple[str, ...] = ("tests",)   # reserved


@dataclass(frozen=True)
class ResearchSettings:
    """Research agent (v1): reads public web pages through the permission-checked browser tool. Opt-in; needs [agents] and [browser]."""
    enabled: bool = False
    max_sources: int = 8               # pages read per task (hard limit 20)
    max_actions: int = 40              # browser tool calls per task (hard limit 200)
    timeout_seconds: float = 300.0     # the whole task (hard limit 1800)
    max_result_chars: int = 20_000     # size of the structured result
    extract_backend: str = "builtin"   # HTML-to-text backend: "builtin" (stdlib, default) or "trafilatura" (optional extra `research`)
    search_enabled: bool = False       # web search through ONE external source (Brave Search API); OFF by default, costs money, sends the query text to the provider
    search_provider: str = "brave"     # the only real source (docs/integrations/research.md); the key comes from the environment (BRAVE_SEARCH_API_KEY), never a file
    search_max_searches: int = 20      # searches per session (hard limit 100)
    search_timeout_seconds: float = 10.0       # per request (hard limit 30)
    search_min_interval_seconds: float = 1.0   # rate limit: minimum pause between two requests (0..60)


@dataclass(frozen=True)
class BusinessSettings:
    """Business agent (v1): turns research results and the user's own numbers into structured analyses. No tools: it computes and drafts, it never sends."""
    enabled: bool = False
    max_steps: int = 20                # computation steps / list items per task (hard limit 100)
    timeout_seconds: float = 120.0     # hard limit 600
    max_result_chars: int = 20_000


@dataclass(frozen=True)
class FinanceSettings:
    """Finance agent (v1): analysis and PAPER trading only. No broker, no orders, no transfers - `paper_trading_only` must stay true."""
    enabled: bool = False
    max_steps: int = 50                # data points / positions / trades per task (hard limit 1000)
    paper_trading_only: bool = True    # false is rejected: live trading does not exist in v1
    timeout_seconds: float = 120.0     # hard limit 600
    max_result_chars: int = 20_000
    max_risk_per_trade_pct: float = 1.0      # risk limits applied to paper trades (prepared for later real-money limits)
    max_position_pct: float = 20.0
    max_total_exposure_pct: float = 100.0
    daily_loss_limit_pct: float = 3.0
    max_leverage: float = 1.0          # 1.0 = no leverage (hard limit 1.0 in v1)


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
    llm_edits: bool = False                 # `propose`: the model DRAFTS edits (never applied by it; each is written via `write`, confirmed one by one)
    llm_edits_max: int = 3                  # most edits one `propose` call may return (1..10)


@dataclass(frozen=True)
class FilesSettings:
    """File tools (A8): list/read/create/write/move/copy/mkdir/organize. Opt-in; no delete action exists; never outside confirmed roots."""
    enabled: bool = False
    roots: tuple[str, ...] = ()        # confirmed directories; () = security.allowed_roots (else the workspace). Must also lie inside the engine's roots
    max_read_chars: int = 20_000       # most characters one `read` returns
    max_file_size: int = 1_000_000     # larger files are neither read, written nor copied
    max_list_entries: int = 500
    max_organize_moves: int = 100      # most steps in one organize plan
    max_actions_per_session: int = 300  # hard stop against runaway loops (reads count too)
    max_actions_per_minute: int = 120


@dataclass(frozen=True)
class OfficeSettings:
    """Office files (office-docs, O1): read and create NEW .xlsx/.docx inside the confirmed workspace. Opt-in; never macros, never overwriting, no delete.
    Needs the optional extra `office` (imported lazily; a missing library gives a clear message)."""
    enabled: bool = False
    roots: tuple[str, ...] = ()          # confirmed directories; () = security.allowed_roots (else the workspace). Must also lie inside the engine's roots
    max_file_size: int = 5_000_000       # larger files are neither read nor written
    max_unpacked_bytes: int = 50_000_000  # zip bomb guard: total size of all parts after unpacking (counted while reading, not from the headers)
    max_zip_entries: int = 2000
    max_sheets: int = 20
    max_rows: int = 1000                 # rows per sheet (read and create)
    max_cols: int = 50
    max_cells: int = 20_000              # cells per call (read) / per file (create)
    max_paragraphs: int = 500            # blocks per call (read) / paragraphs per file (create)
    max_read_chars: int = 20_000         # most characters one `read` returns
    read_timeout_seconds: float = 10.0   # parsing time limit (cooperative: checked per row / block)
    max_actions_per_session: int = 100   # hard stop against runaway loops (reads count too)
    max_actions_per_minute: int = 30


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
    history: HistorySettings = field(default_factory=HistorySettings)
    journal: JournalSettings = field(default_factory=JournalSettings)
    assistant: AssistantSettings = field(default_factory=AssistantSettings)
    control_center: ControlCenterSettings = field(default_factory=ControlCenterSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    computer: ComputerSettings = field(default_factory=ComputerSettings)
    browser: BrowserSettings = field(default_factory=BrowserSettings)
    coding: CodingSettings = field(default_factory=CodingSettings)
    files: FilesSettings = field(default_factory=FilesSettings)
    office: OfficeSettings = field(default_factory=OfficeSettings)
    agents: AgentsSettings = field(default_factory=AgentsSettings)
    goals: GoalsSettings = field(default_factory=GoalsSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    llm_routing: RoutingSettings = field(default_factory=RoutingSettings)
    llm_budget: LlmBudgetSettings = field(default_factory=LlmBudgetSettings)
    self_repair: SelfRepairSettings = field(default_factory=SelfRepairSettings)
    self_improvement: SelfImprovementSettings = field(default_factory=SelfImprovementSettings)
    research: ResearchSettings = field(default_factory=ResearchSettings)
    business: BusinessSettings = field(default_factory=BusinessSettings)
    finance: FinanceSettings = field(default_factory=FinanceSettings)

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

    def _validate_llm_budget(self) -> None:
        lb = self.llm_budget
        try:
            lb.to_limits()
            lb.to_prices()
        except ValueError as exc:
            raise ConfigError(f"llm_budget: {exc}") from None
        if lb.max_input_tokens_per_call > lb.max_input_tokens_session or lb.max_input_tokens_session > lb.max_tokens_session:
            raise ConfigError("llm_budget: max_input_tokens_per_call must not exceed max_input_tokens_session, which must not exceed max_tokens_session")

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
        if v.vad_min_speech_seconds < 0:
            raise ConfigError("voice.vad_min_speech_seconds must be >= 0")
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
        if not 1 <= c.uia_max_calls_per_session <= 10_000 or not 0 < c.uia_call_timeout <= 600:
            raise ConfigError("computer.uia_max_calls_per_session must be 1..10000 and uia_call_timeout 0..600 seconds")
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
        if not 1 <= cd.llm_edits_max <= 10:
            raise ConfigError("coding.llm_edits_max must be 1..10")
        fs = self.files
        if any(not r.strip() for r in fs.roots):
            raise ConfigError("files.roots must not contain empty entries")
        if not 100 <= fs.max_read_chars <= 500_000 or not 100 <= fs.max_file_size <= 50_000_000:
            raise ConfigError("files.max_read_chars 100..500000, max_file_size 100..50000000")
        if not 1 <= fs.max_list_entries <= 20000 or not 1 <= fs.max_organize_moves <= 1000:
            raise ConfigError("files.max_list_entries 1..20000, max_organize_moves 1..1000")
        if fs.max_actions_per_session < 0 or fs.max_actions_per_minute < 0:
            raise ConfigError("files.max_actions_per_session/max_actions_per_minute must be >= 0")
        of = self.office
        if any(not r.strip() for r in of.roots):
            raise ConfigError("office.roots must not contain empty entries")
        if not 1000 <= of.max_file_size <= 50_000_000 or not 10_000 <= of.max_unpacked_bytes <= 500_000_000 or not 1 <= of.max_zip_entries <= 20_000:
            raise ConfigError("office.max_file_size 1000..50000000, max_unpacked_bytes 10000..500000000, max_zip_entries 1..20000")
        if not 1 <= of.max_sheets <= 100 or not 1 <= of.max_rows <= 100_000 or not 1 <= of.max_cols <= 1000 or not 1 <= of.max_cells <= 1_000_000 \
                or not 1 <= of.max_paragraphs <= 20_000 or not 100 <= of.max_read_chars <= 500_000:
            raise ConfigError("office.max_sheets 1..100, max_rows 1..100000, max_cols 1..1000, max_cells 1..1000000, max_paragraphs 1..20000, max_read_chars 100..500000")
        if not 0 < of.read_timeout_seconds <= 300 or of.max_actions_per_session < 0 or of.max_actions_per_minute < 0:
            raise ConfigError("office.read_timeout_seconds 0..300 (positive); max_actions_per_session/max_actions_per_minute must be >= 0")
        ag = self.agents
        if not 1 <= ag.max_concurrent <= 16 or not 0 < ag.task_timeout_seconds <= 3600 or not 1 <= ag.max_queue <= 1000:
            raise ConfigError("agents.max_concurrent 1..16, task_timeout_seconds 0..3600 (positive), max_queue 1..1000")
        if not 1 <= ag.max_history <= 10_000 or not 0 <= ag.cancel_grace_seconds <= 300 or not 1 <= ag.tool_call_limit <= 5000 \
                or not 1_000 <= ag.max_output_chars <= 1_000_000:
            raise ConfigError("agents.max_history 1..10000, cancel_grace_seconds 0..300, tool_call_limit 1..5000, max_output_chars 1000..1000000")
        rt = ag.router
        if not 0 < rt.timeout_seconds <= 60 or not 1 <= rt.max_objective_chars <= 2000 or not 1 <= rt.max_reason_chars <= 300:
            raise ConfigError("agents.router.timeout_seconds 0..60 (positive), max_objective_chars 1..2000, max_reason_chars 1..300")
        gl = self.goals
        if not 1 <= gl.max_steps <= 50 or not 1 <= gl.max_attempts_per_step <= 5:
            raise ConfigError("goals.max_steps 1..50, max_attempts_per_step 1..5")
        if not 0 < gl.goal_timeout_seconds <= 86_400 or not 0 < gl.step_timeout_seconds <= 3600 or not 1 <= gl.max_active_goals <= 8 \
                or not 1 <= gl.max_history <= 1000:
            raise ConfigError("goals.goal_timeout_seconds 0..86400, step_timeout_seconds 0..3600 (positive), max_active_goals 1..8, max_history 1..1000")
        bu = self.budget
        if not 1 <= bu.max_tool_calls <= 100_000 or not 0 < bu.max_runtime_seconds <= 86_400:
            raise ConfigError("budget.max_tool_calls 1..100000, max_runtime_seconds 0..86400 (positive)")
        lr = self.llm_routing
        bad = [t for t in lr.cloud_tasks if t not in ROUTING_TASKS or t == "speech"]
        if bad:
            raise ConfigError(f"llm_routing.cloud_tasks: unknown or forbidden task class {bad!r}; allowed: {[t for t in ROUTING_TASKS if t != 'speech']}")
        if lr.enabled and not lr.local_provider and not lr.cloud_provider:
            raise ConfigError("llm_routing.enabled needs local_provider and/or cloud_provider")
        if lr.enabled and lr.local_provider and lr.local_provider.lower() == lr.cloud_provider.lower():
            raise ConfigError("llm_routing.local_provider and cloud_provider must differ")
        self._validate_llm_budget()
        si = self.self_improvement
        if not 1 <= si.max_proposals <= 2000 or not 1 <= si.min_occurrences <= 50 or not 1 <= si.max_edits <= 10 or not 1000 <= si.max_diff_bytes <= 500_000 \
                or not 0 < si.prepare_timeout_seconds <= 600 or not 0 < si.test_timeout_seconds <= 3600:
            raise ConfigError("self_improvement.max_proposals 1..2000, min_occurrences 1..50, max_edits 1..10, max_diff_bytes 1000..500000, prepare_timeout_seconds 0..600, test_timeout_seconds 0..3600 (positive)")
        if si.allow_prepare or si.allow_activation or si.repo_path.strip():
            raise ConfigError("self_improvement.allow_prepare, allow_activation and repo_path are not available in this version: proposed code is never prepared, tested or "
                              "activated until execution isolation is proven (see src/jarvis/self_improvement/isolation.py)")
        if not si.data_dir.strip() or not si.regression_paths or any(not r.strip() or r.startswith(("/", "\\")) or ".." in r for r in si.regression_paths):
            raise ConfigError("self_improvement.data_dir must not be empty; regression_paths must be relative paths inside the repository")
        sr = self.self_repair
        if not 1 <= sr.max_attempts <= 5 or not 0 < sr.repair_timeout_seconds <= 3600 or not 0 < sr.step_timeout_seconds <= 3600 \
                or not 1 <= sr.max_active_repairs <= 4 or not 1 <= sr.max_history <= 500:
            raise ConfigError("self_repair.max_attempts 1..5, repair_timeout_seconds/step_timeout_seconds 0..3600 (positive), max_active_repairs 1..4, max_history 1..500")
        rs, bs, fs = self.research, self.business, self.finance
        if not 1 <= rs.max_sources <= 20 or not 1 <= rs.max_actions <= 200 or not 0 < rs.timeout_seconds <= 1800 or not 1000 <= rs.max_result_chars <= 100_000:
            raise ConfigError("research.max_sources 1..20, max_actions 1..200, timeout_seconds 0..1800 (positive), max_result_chars 1000..100000")
        if rs.extract_backend not in ("builtin", "trafilatura"):
            raise ConfigError("research.extract_backend must be 'builtin' or 'trafilatura'")
        if rs.search_provider != "brave" or not 1 <= rs.search_max_searches <= 100 or not 0 < rs.search_timeout_seconds <= 30 \
                or not 0 <= rs.search_min_interval_seconds <= 60:
            raise ConfigError("research.search_provider must be 'brave'; search_max_searches 1..100, search_timeout_seconds 0..30 (positive), search_min_interval_seconds 0..60")
        if not 1 <= bs.max_steps <= 100 or not 0 < bs.timeout_seconds <= 600 or not 1000 <= bs.max_result_chars <= 100_000:
            raise ConfigError("business.max_steps 1..100, timeout_seconds 0..600 (positive), max_result_chars 1000..100000")
        if not 1 <= fs.max_steps <= 1000 or not 0 < fs.timeout_seconds <= 600 or not 1000 <= fs.max_result_chars <= 100_000:
            raise ConfigError("finance.max_steps 1..1000, timeout_seconds 0..600 (positive), max_result_chars 1000..100000")
        if not fs.paper_trading_only:
            raise ConfigError("finance.paper_trading_only must stay true: live trading, orders and transfers do not exist in this version")
        if not (0 < fs.max_risk_per_trade_pct <= 5 and 0 < fs.max_position_pct <= 100 and 0 < fs.max_total_exposure_pct <= 100
                and 0 < fs.daily_loss_limit_pct <= 20 and fs.max_leverage == 1.0):
            raise ConfigError("finance risk limits: max_risk_per_trade_pct 0..5, max_position_pct 0..100, max_total_exposure_pct 0..100, daily_loss_limit_pct 0..20, max_leverage 1.0")
        m = self.memory
        if not m.backend.strip():
            raise ConfigError("memory.backend must not be empty")
        if m.backend.lower() in ("sqlite", "semantic") and not m.path.strip():
            raise ConfigError("memory.path must not be empty for the sqlite backend")
        if m.max_relevant < 0 or m.max_entries < 0:
            raise ConfigError("memory.max_relevant/max_entries must be >= 0")
        if m.recent_limit <= 0 or m.max_content_length <= 0:
            raise ConfigError("memory.recent_limit/max_content_length must be positive")
        hi = self.history
        if not hi.path.strip() or not 1 <= hi.max_entries <= 100_000 or not 1 <= hi.max_text_length <= 2000:
            raise ConfigError("history.path must not be empty, max_entries 1..100000, max_text_length 1..2000")
        jo = self.journal
        if not jo.path.strip() or not 1 <= jo.max_entries <= 100_000 or not 1 <= jo.max_steps_per_entry <= 200 \
                or not 1 <= jo.max_text_length <= 2000 or not 1 <= jo.max_evidence <= 20:
            raise ConfigError("journal.path must not be empty, max_entries 1..100000, max_steps_per_entry 1..200, max_text_length 1..2000, max_evidence 1..20")
        if not 1.0 <= self.assistant.confirmation_timeout_seconds <= 600.0:
            raise ConfigError("assistant.confirmation_timeout_seconds must be 1..600")
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

    file_llm_key = settings.llm.api_key
    settings = _apply_env(settings, env)
    if settings.llm.provider == "openai_compatible" and file_llm_key and file_llm_key == settings.llm.api_key and \
            file_llm_key != env.get("JARVIS_LLM_API_KEY"):
        raise ConfigError("llm.api_key must not be set in a file for openai_compatible; use the environment (JARVIS_LLM_API_KEY)")

    # API keys: provider-specific env var unless an explicit JARVIS_*_API_KEY was given.
    llm_key_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai_compatible": "OPENAI_COMPATIBLE_API_KEY"}.get(settings.llm.provider)
    if settings.llm.api_key is None and llm_key_var and env.get(llm_key_var):
        settings = replace(settings, llm=replace(settings.llm, api_key=env[llm_key_var]))
    if settings.voice.api_key is None and env.get("OPENAI_API_KEY") and "openai" in (
            settings.voice.stt_provider, settings.voice.tts_provider):
        settings = replace(settings, voice=replace(settings.voice, api_key=env["OPENAI_API_KEY"]))
    return settings.validate()
