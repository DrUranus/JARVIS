"""WP01 (V2-06): typed hand-over artifacts between agents - an ISOLATED, backward-compatible core.

Wired (E5, agents.artifacts, OFF by default) ONLY into the orchestrator's result check and the research hand-over (`research/agent.py`, `research/handoff.py`); a layering test keeps it that way. Pure data and checks: no file, network,
process or thread access. An artifact is plain data (kind, source, SHA-256, length, content, redaction flag, basis); it carries NO right: it can neither grant a permission nor
change a plan, and its text is never an instruction. `file_ref` holds only a plain relative path - nothing here ever reads a file (PathGuard stays the one gate).

Producer side: `make_artifact` (raises `ArtifactError` for a programmer error). Receiver side: `accept` NEVER raises for foreign input - every bad artifact becomes a `Rejection`
with a stable code. Old `output` dicts without an `artifacts` block stay valid (`artifacts_of` -> []).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jarvis.agents import policy as AP
from jarvis.agents.errors import AgentError, InvalidTaskError
from jarvis.agents.models import check_json, clean_json
from jarvis.redaction import SecretDetector

KINDS = ("text", "table", "file_ref", "url_list", "research_data", "diff", "summary")
BASES = ("GIVEN", "FACT", "INFERENCE", "ESTIMATE")
# Upper bound of the CANONICAL JSON length (characters) per kind. They stay below the shared agent limits (MAX_TEXT, MAX_INPUT_BYTES).
LIMITS = {"text": AP.MAX_TEXT, "summary": 2_000, "diff": AP.MAX_INPUT_BYTES, "research_data": AP.MAX_INPUT_BYTES, "table": 50_000,
          "url_list": AP.MAX_INPUT_BYTES, "file_ref": 400}
MAX_ARTIFACTS = 20
MAX_URLS, MAX_URL_LEN = 100, 2000
MAX_COLUMNS, MAX_ROWS = 50, 1000
MAX_PATH = 300
_SHA = re.compile(r"^[0-9a-f]{64}$")
_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
_CREDS_IN_URL = re.compile(r"^https?://[^/?#]*@", re.IGNORECASE)
_DRIVE = re.compile(r"^[A-Za-z]:")
_RESERVED = frozenset(k.lower() for k in AP.RESERVED_TOOL_ARGS)
_DETAIL = 120


class ArtifactError(AgentError):
    """Producer-side problem; `code` is one of the stable codes below."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Artifact:
    kind: str
    source_agent: str
    source_task: str
    sha256: str
    length: int
    content: Any
    redacted: bool = True
    basis: str = "INFERENCE"


@dataclass(frozen=True)
class Rejection:
    index: int
    code: str
    detail: str = ""


@dataclass(frozen=True)
class AcceptResult:
    accepted: tuple[Artifact, ...] = ()
    rejected: tuple[Rejection, ...] = ()


def _short(value: Any) -> str:
    return str(value)[:_DETAIL].replace("\n", " ")


def canonical(content: Any) -> str:
    """Stable JSON text of `content` (sorted keys, no spaces); the hash and the length refer to exactly this text."""
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(text: str) -> str:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise ArtifactError("bad_content", "text is not valid unicode") from None


def _scan_reserved(value: Any, depth: int = 0) -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _RESERVED:
                raise ArtifactError("bad_content", f"reserved key {k!r}")
            _scan_reserved(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _scan_reserved(v, depth + 1)


def _redact(value: Any, det: SecretDetector) -> Any:
    if isinstance(value, str):
        return det.redact(value)
    if isinstance(value, Mapping):
        return {k: _redact(v, det) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, det) for v in value]
    return value


def _plain_path(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip() or len(path) > MAX_PATH or "\x00" in path or any(ord(c) < 32 for c in path):
        return False
    p = path.replace("\\", "/")
    if p.startswith(("/", "~")) or _DRIVE.match(p) or p.startswith("//"):
        return False
    parts = [c for c in p.split("/") if c not in ("", ".")]
    return bool(parts) and not any(c == ".." or c.endswith((" ", ".")) for c in parts)


def _check_shape(kind: str, content: Any) -> None:
    """Kind-specific shape; the generic checks (plain JSON, depth, reserved keys) have already run."""
    if kind in ("text", "summary", "diff"):
        if not isinstance(content, str):
            raise ArtifactError("bad_content", f"{kind} content must be text")
    elif kind == "table":
        cols = content.get("columns") if isinstance(content, Mapping) else None
        rows = content.get("rows") if isinstance(content, Mapping) else None
        if (not isinstance(cols, list) or not cols or len(cols) > MAX_COLUMNS or not all(isinstance(c, str) for c in cols)
                or not isinstance(rows, list) or set(content) - {"columns", "rows"}):
            raise ArtifactError("bad_content", "table needs columns (text list) and rows (list)")
        if len(rows) > MAX_ROWS:
            raise ArtifactError("too_large", "too many rows")
        if any(not isinstance(r, list) or len(r) != len(cols) for r in rows):
            raise ArtifactError("bad_content", "every row must match the columns")
    elif kind == "url_list":
        if not isinstance(content, list) or not all(isinstance(u, str) for u in content):
            raise ArtifactError("bad_content", "url_list must be a list of text")
        if len(content) > MAX_URLS:
            raise ArtifactError("too_large", "too many urls")
        for u in content:
            if len(u) > MAX_URL_LEN or not _URL.match(u) or _CREDS_IN_URL.match(u):
                raise ArtifactError("bad_content", "only plain http(s) urls without credentials")
    elif kind == "file_ref":
        if not isinstance(content, Mapping) or set(content) != {"path"} or not _plain_path(content.get("path")):
            raise ArtifactError("bad_content", "file_ref needs a plain relative path and nothing else")
    elif kind == "research_data":
        if not isinstance(content, Mapping):
            raise ArtifactError("bad_content", "research_data must be an object")


def _validate(kind: Any, source_agent: Any, source_task: Any, basis: Any, content: Any) -> Any:
    """Returns a plain deep copy of `content`; raises ArtifactError otherwise."""
    if not isinstance(kind, str) or kind not in KINDS:
        raise ArtifactError("kind_unknown", _short(kind))
    if not AP.valid_agent_id(source_agent) or not AP.valid_id(source_task):
        raise ArtifactError("bad_source", "source_agent / source_task are not valid ids")
    if basis not in BASES:
        raise ArtifactError("bad_basis", _short(basis))
    try:
        check_json(content, "artifact content")
    except InvalidTaskError as exc:
        raise ArtifactError("bad_content", _short(exc)) from None
    plain = clean_json(content)
    _scan_reserved(plain)
    _check_shape(kind, plain)
    return plain


def _build(kind: str, source_agent: str, source_task: str, basis: str, plain: Any, det: SecretDetector) -> Artifact:
    clean = _redact(plain, det)
    text = canonical(clean)
    if len(text) > LIMITS[kind]:
        raise ArtifactError("too_large", f"{kind} exceeds {LIMITS[kind]} characters")
    return Artifact(kind, source_agent, source_task, _digest(text), len(text), clean, True, basis)


def make_artifact(kind: str, content: Any, *, source_agent: str, source_task: str, basis: str = "INFERENCE",
                  detector: SecretDetector | None = None) -> Artifact:
    """Producer side: validates, redacts, hashes. Raises ArtifactError (a programmer error, never foreign input)."""
    plain = _validate(kind, source_agent, source_task, basis, content)
    return _build(kind, source_agent, source_task, basis, plain, detector or SecretDetector.from_environment())


def verify(artifact: Artifact) -> bool:
    """True if hash and length still match the content (False for anything that is not a valid artifact). Never raises."""
    try:
        if not isinstance(artifact, Artifact) or artifact.kind not in KINDS:
            return False
        text = canonical(artifact.content)
        return len(text) == artifact.length and len(text) <= LIMITS[artifact.kind] and _digest(text) == artifact.sha256
    except Exception:  # noqa: BLE001 - verification must never raise
        return False


def to_dict(artifact: Artifact) -> dict[str, Any]:
    """A plain, independent copy (JSON-compatible) for transport inside an agent `output`."""
    return {"kind": artifact.kind, "source_agent": artifact.source_agent, "source_task": artifact.source_task, "sha256": artifact.sha256,
            "length": artifact.length, "content": clean_json(artifact.content), "redacted": artifact.redacted, "basis": artifact.basis}


def artifacts_of(output: Any) -> list[Any]:
    """The optional `artifacts` block of an agent output; anything else (old outputs, None, wrong types) -> []."""
    if isinstance(output, Mapping):
        block = output.get("artifacts")
        if isinstance(block, (list, tuple)):
            return list(block)
    return []


def _receive(raw: Any, declared: frozenset[str], det: SecretDetector) -> Artifact:
    if not isinstance(raw, Mapping):
        raise ArtifactError("artifact_invalid", "not an object")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ArtifactError("kind_unknown", _short(kind))
    if kind not in declared:
        raise ArtifactError("kind_not_declared", kind)
    sha, length = raw.get("sha256"), raw.get("length")
    if not isinstance(sha, str) or not _SHA.match(sha) or isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise ArtifactError("artifact_invalid", "sha256 / length malformed")
    if "content" not in raw:
        raise ArtifactError("artifact_invalid", "content missing")
    plain = _validate(kind, raw.get("source_agent"), raw.get("source_task"), raw.get("basis"), raw.get("content"))
    text = canonical(plain)
    if len(text) > LIMITS[kind]:
        raise ArtifactError("too_large", f"{kind} exceeds {LIMITS[kind]} characters")
    if len(text) != length or _digest(text) != sha:
        raise ArtifactError("hash_mismatch", "content does not match sha256 / length")
    return _build(kind, raw["source_agent"], raw["source_task"], raw["basis"], plain, det)   # redacts again; unchanged content keeps the same hash


def accept(raws: Iterable[Any], declared_kinds: Iterable[str], *, detector: SecretDetector | None = None,
           max_artifacts: int = MAX_ARTIFACTS) -> AcceptResult:
    """Receiver side. Only DECLARED kinds arrive; invalid artifacts are dropped with a code (no partial takeover, no exception). Order is kept, count is limited."""
    try:
        declared = frozenset(k for k in declared_kinds if isinstance(k, str))
        det = detector or SecretDetector.from_environment()
        items = list(raws) if isinstance(raws, (list, tuple)) else []
    except Exception:  # noqa: BLE001
        return AcceptResult()
    limit = max(0, min(max_artifacts, MAX_ARTIFACTS))
    accepted: list[Artifact] = []
    rejected: list[Rejection] = []
    for i, raw in enumerate(items):
        if len(accepted) >= limit:
            rejected.append(Rejection(i, "too_many", f"more than {limit} artifacts"))
            continue
        try:
            accepted.append(_receive(raw, declared, det))
        except ArtifactError as exc:
            rejected.append(Rejection(i, exc.code, exc.detail))
        except Exception as exc:  # noqa: BLE001 - foreign input must never crash the receiver
            rejected.append(Rejection(i, "artifact_invalid", type(exc).__name__))
    return AcceptResult(tuple(accepted), tuple(rejected))
