"""UI-Vertrag v1: Form und Pruefung aller Ereignisse (Backend -> Oberflaeche) und Befehle (Oberflaeche -> Backend). Nur Standardbibliothek.

Streng: genau die vorgesehenen Felder, begrenzte Laengen, geschlossene Typmengen; Steuerzeichen in Texten werden ersetzt. Dieselbe Beschreibung erzeugt die JSON-Schemas fuer das
Frontend (`schema/*.schema.json`). Der Vertrag kennt keinen Befehl, der Rechte erteilt, Regeln aendert, ein Werkzeug direkt ausfuehrt oder den Notaus aufhebt."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

VERSION = "1.0"
_MAJOR = VERSION.split(".")[0]
MAX_TEXT, MAX_SHORT, MAX_LABEL, MAX_ITEMS, MAX_CONTEXT, MAX_ARTIFACTS = 4000, 200, 300, 200, 10, 50
MAX_COMMAND_BYTES = 16_000

STATES = ("ready", "listening", "processing", "speaking", "awaiting_confirmation", "error", "emergency")
PERMISSION_LEVELS = ("green", "yellow", "red")
CHOICES = ("allow_once", "allow_session", "deny")
OUTCOMES = ("allow_once", "allow_session", "denied", "timeout", "cancelled")
ACTIVITY_KINDS = ("goal", "agent_task", "repair", "plan", "resume")
SENDERS = ("user", "jarvis", "system")
SOURCES = ("llm", "rules")
ARTIFACT_KINDS = ("file", "text", "link", "table")

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_ID = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")
_VERSION_RE = re.compile(rf"{_MAJOR}\.\d{{1,3}}")


class ContractError(ValueError):
    """The message does not follow the contract (the text names the problem, never the content)."""


# ---- kleine Beschreibungssprache (pruefen UND JSON-Schema erzeugen) -----------------------------------------------------------------------
class Str:
    def __init__(self, max_len: int = MAX_SHORT, min_len: int = 0, pattern: re.Pattern[str] | None = None) -> None:
        self.max_len, self.min_len, self.pattern = max_len, min_len, pattern

    def check(self, v: Any, path: str) -> str:
        if not isinstance(v, str):
            raise ContractError(f"{path}: text expected")
        v = _CONTROL.sub(" ", v)
        if self.pattern is not None:
            if not self.pattern.fullmatch(v):
                raise ContractError(f"{path}: invalid format")
        elif not self.min_len <= len(v) <= self.max_len:
            raise ContractError(f"{path}: length must be {self.min_len}..{self.max_len}")
        return v

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "string"}
        if self.pattern is not None:
            out["pattern"] = self.pattern.pattern
        else:
            out["maxLength"] = self.max_len
            if self.min_len:
                out["minLength"] = self.min_len
        return out


class Enum:
    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = values

    def check(self, v: Any, path: str) -> str:
        if not isinstance(v, str) or v not in self.values:
            raise ContractError(f"{path}: one of {list(self.values)} expected")
        return v

    def schema(self) -> dict[str, Any]:
        return {"enum": list(self.values)}


class Bool:
    def check(self, v: Any, path: str) -> bool:
        if not isinstance(v, bool):
            raise ContractError(f"{path}: true or false expected")
        return v

    def schema(self) -> dict[str, Any]:
        return {"type": "boolean"}


class Num:
    def __init__(self, lo: float, hi: float) -> None:
        self.lo, self.hi = lo, hi

    def check(self, v: Any, path: str) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not self.lo <= v <= self.hi:
            raise ContractError(f"{path}: number between {self.lo:g} and {self.hi:g} expected")
        return v

    def schema(self) -> dict[str, Any]:
        return {"type": "number", "minimum": self.lo, "maximum": self.hi}


class List:
    def __init__(self, item: Any, max_len: int, min_len: int = 0) -> None:
        self.item, self.max_len, self.min_len = item, max_len, min_len

    def check(self, v: Any, path: str) -> list[Any]:
        if not isinstance(v, list) or not self.min_len <= len(v) <= self.max_len:
            raise ContractError(f"{path}: list of {self.min_len}..{self.max_len} entries expected")
        return [self.item.check(x, f"{path}[{i}]") for i, x in enumerate(v)]

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "array", "items": self.item.schema(), "maxItems": self.max_len}
        if self.min_len:
            out["minItems"] = self.min_len
        return out


class Obj:
    """Exactly these fields; `optional` ones may be missing (then absent from the result)."""

    def __init__(self, fields: dict[str, Any], optional: tuple[str, ...] = ()) -> None:
        self.fields, self.optional = fields, optional

    def check(self, v: Any, path: str) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ContractError(f"{path}: object expected")
        extra = sorted(set(v) - set(self.fields))
        if extra:
            raise ContractError(f"{path}: unknown field {extra[0]!r}")
        out: dict[str, Any] = {}
        for name, spec in self.fields.items():
            if name not in v:
                if name in self.optional:
                    continue
                raise ContractError(f"{path}: field {name!r} is missing")
            out[name] = spec.check(v[name], f"{path}.{name}")
        return out

    def schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {k: s.schema() for k, s in self.fields.items()},
                "required": [k for k in self.fields if k not in self.optional], "additionalProperties": False}


ID = Str(pattern=_ID)
SHORT, LABEL, TEXT = Str(MAX_SHORT), Str(MAX_LABEL), Str(MAX_TEXT)
ACTIVITY_ITEM = Obj({"kind": Enum(ACTIVITY_KINDS), "id": ID, "title": SHORT, "status": Str(32), "note": SHORT, "cancellable": Bool()})

EVENT_SPECS: dict[str, Obj] = {
    "hello": Obj({"contract": Str(16), "backend": Str(64), "capabilities": List(Str(32), 32), "emergency": Bool()}),
    "state": Obj({"state": Enum(STATES), "detail": SHORT}, optional=("detail",)),
    "chat": Obj({"sender": Enum(SENDERS), "text": TEXT}),
    "activity": Obj({"items": List(ACTIVITY_ITEM, MAX_ITEMS), "problems": List(SHORT, 20), "inactive": List(Str(64), 20)}),
    "task_update": Obj({"kind": Enum(ACTIVITY_KINDS), "id": ID, "status": Str(32), "detail": SHORT}, optional=("detail",)),
    "routing": Obj({"task_id": ID, "agent": Str(64), "source": Enum(SOURCES), "reason": LABEL}),
    "result": Obj({"task_id": ID, "summary": TEXT, "artifacts": List(Obj({"name": Str(120), "kind": Enum(ARTIFACT_KINDS), "ref": LABEL}), MAX_ARTIFACTS)}),
    "confirmation_request": Obj({"request_id": ID, "tool": Str(64), "action": Str(64), "resource": LABEL, "level": Enum(PERMISSION_LEVELS), "reason": LABEL,
                                 "context": List(Obj({"key": Str(64), "value": LABEL}), MAX_CONTEXT), "choices": List(Enum(CHOICES), 3, 1), "timeout_s": Num(1, 600)}),
    "confirmation_closed": Obj({"request_id": ID, "outcome": Enum(OUTCOMES)}),
    "emergency": Obj({"engaged": Bool(), "reason": SHORT, "report": List(SHORT, 20)}),
    "voice_level": Obj({"level": Num(0, 1), "active": Bool()}),
    "error": Obj({"code": Str(64), "message": LABEL}),
    "ack": Obj({"id": ID, "ok": Bool(), "code": Str(64), "message": LABEL}),
}
COMMAND_SPECS: dict[str, Obj] = {
    "submit_text": Obj({"text": Str(MAX_TEXT, 1)}),
    "start_voice": Obj({}),
    "stop_voice": Obj({}),
    "cancel": Obj({"kind": Enum(ACTIVITY_KINDS), "id": ID}),
    "confirm": Obj({"request_id": ID, "choice": Enum(CHOICES)}),
    "emergency_stop": Obj({}),
    "reset_emergency": Obj({}),            # only a REQUEST: the permission engine asks the human itself; nothing is lifted by this message
    "request_snapshot": Obj({}),
}
EVENT_TYPES = tuple(EVENT_SPECS)
COMMAND_TYPES = tuple(COMMAND_SPECS)


def _version(v: Any) -> str:
    if not isinstance(v, str) or not _VERSION_RE.fullmatch(v):
        raise ContractError(f"v: contract version {_MAJOR}.x expected")
    return v


def validate_event(obj: Any) -> dict[str, Any]:
    """The normalised event or ContractError."""
    if not isinstance(obj, dict) or set(obj) != {"v", "seq", "ts", "type", "data"}:
        raise ContractError("event: exactly v, seq, ts, type, data expected")
    seq, ts = obj["seq"], obj["ts"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ContractError("seq: positive integer expected")
    if not isinstance(ts, str) or not _TS.fullmatch(ts):
        raise ContractError("ts: UTC time like 2026-11-02T10:00:00Z expected")
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ContractError("ts: not a valid time") from None
    spec = EVENT_SPECS.get(obj["type"]) if isinstance(obj["type"], str) else None
    if spec is None:
        raise ContractError("type: unknown event type")
    return {"v": _version(obj["v"]), "seq": seq, "ts": ts, "type": obj["type"], "data": spec.check(obj["data"], "data")}


def validate_command(obj: Any) -> dict[str, Any]:
    """The normalised command or ContractError."""
    if not isinstance(obj, dict) or set(obj) != {"v", "id", "type", "data"}:
        raise ContractError("command: exactly v, id, type, data expected")
    spec = COMMAND_SPECS.get(obj["type"]) if isinstance(obj["type"], str) else None
    if spec is None:
        raise ContractError("type: unknown command type")
    return {"v": _version(obj["v"]), "id": ID.check(obj["id"], "id"), "type": obj["type"], "data": spec.check(obj["data"], "data")}


def parse_command(text: str | bytes) -> dict[str, Any]:
    """From the wire: size limit first, then JSON (no NaN/Infinity), then the contract."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    if len(raw) > MAX_COMMAND_BYTES:
        raise ContractError("command: too large")
    def no_constant(name: str) -> Any:
        raise ValueError(name)
    try:
        obj = json.loads(raw.decode("utf-8"), parse_constant=no_constant)
    except (ValueError, UnicodeDecodeError):
        raise ContractError("command: not valid JSON") from None
    return validate_command(obj)


_SECRET_PATTERNS = (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
                    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), re.compile(r"(?i)(?:passwor[dt]|passwd|token|api[_\- ]?key|secret|kennwort)\s*[=:]\s*\S{4,}"))


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def redact_text(text: str) -> str:
    """Minimal protection inside the contract package (the real backends use jarvis.redaction before they emit anything)."""
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


# ---- JSON-Schema fuer das Frontend ---------------------------------------------------------------------------------------------------------------
def _schema(title: str, specs: dict[str, Obj], key: str, key_schema: dict[str, Any]) -> dict[str, Any]:
    ver = {"type": "string", "pattern": _VERSION_RE.pattern}
    branches = []
    for name, spec in specs.items():
        props = {"v": ver, key: key_schema, "type": {"const": name}, "data": spec.schema()}
        if key == "seq":
            props["ts"] = {"type": "string", "pattern": _TS.pattern}
        branches.append({"type": "object", "properties": props, "required": ["v", key, *(["ts"] if key == "seq" else []), "type", "data"], "additionalProperties": False})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": title, "oneOf": branches}


def event_schema() -> dict[str, Any]:
    return _schema(f"JARVIS UI events v{VERSION}", EVENT_SPECS, "seq", {"type": "integer", "minimum": 1})


def command_schema() -> dict[str, Any]:
    return _schema(f"JARVIS UI commands v{VERSION}", COMMAND_SPECS, "id", ID.schema())


def write_schema_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, schema in (("ui-events.schema.json", event_schema()), ("ui-commands.schema.json", command_schema())):
        (directory / name).write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_schema_files(Path(__file__).resolve().parent / "schema")
    print("schema files written", file=sys.stderr)
