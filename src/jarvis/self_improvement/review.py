"""Review of a change from Git METADATA and BLOB CONTENT, never from the text of `git diff`.

The set of changed files comes from `git diff-tree --raw` (status, modes, blob ids), which no `.gitattributes` / `-diff` / binary rule can hide. Every changed
file must be an existing, allow-listed Python file with an unchanged regular-file mode; old and new blob are read from the object database, their SHA-1 is
recomputed, they must be strict UTF-8 text without NUL, and the complete new module is reviewed by the AST scan (policy.new_findings). The diff shown to the
user is generated here from those blobs (difflib), not taken from git. A change that cannot be read, displayed or classified completely is BLOCKED.
Nothing here imports or executes the reviewed code."""
from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Sequence

from jarvis.self_improvement import policy as P
from jarvis.self_improvement.errors import ChangeBlocked

MAX_VIEW_LINES = 300
MAX_VIEW_LINE_CHARS = 200
MAX_FILE_BYTES = 200_000
REGULAR_MODE = "100644"


@dataclass(frozen=True)
class RawEntry:
    status: str
    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    path: str


@dataclass(frozen=True)
class FileChange:
    path: str
    old_sha: str
    new_sha: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class ReviewedChange:
    base_commit: str
    head_commit: str
    files: tuple[FileChange, ...]
    diff_digest: str                     # sha256 over base, head and (path, old blob, new blob) of every file
    view: tuple[str, ...]                # complete, bounded, escaped diff lines (what the user is shown)
    stat: str

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.files)

    @property
    def view_digest(self) -> str:
        return hashlib.sha256("\n".join(self.view).encode("utf-8")).hexdigest()[:32]


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git object id, not a security hash on its own (sha256 below is)


def change_digest(base: str, head: str, files: Sequence[tuple[str, str, str]]) -> str:
    doc = json.dumps({"base": base, "head": head, "files": [list(f) for f in files]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(doc.encode("ascii")).hexdigest()[:32]


def _decode(data: bytes, path: str) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ChangeBlocked(f"{P.clip(ascii(path), 80)}: file too large to review completely")
    if b"\x00" in data:
        raise ChangeBlocked(f"{P.clip(ascii(path), 80)}: binary content cannot be reviewed")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ChangeBlocked(f"{P.clip(ascii(path), 80)}: not valid UTF-8 text") from None


def render_lines(old: str, new: str, path: str) -> list[str]:
    """Escaped unified diff lines. Every content line is shown through ascii() (control, bidi and look-alike characters become visible escapes) behind a fixed
    prefix; a line that is too long to show completely is a reason to refuse, not to truncate silently."""
    out = [f"--- {P.clip(ascii(path), 120)}"]
    for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2):
        if ln.startswith(("---", "+++")) and len(out) < 2:
            continue
        if ln.startswith(("---", "+++")) and ln[3:4] in (" ", ""):
            ln = ln[:1] + " " + ln[1:]                         # a content line "-- x" can never look like a header
        tag = ln[:1] if ln[:1] in "+- @" else "?"
        body = ascii(ln[1:] if tag in "+- " else ln)[1:-1]
        if len(body) > MAX_VIEW_LINE_CHARS:
            raise ChangeBlocked(f"{P.clip(ascii(path), 80)}: a changed line is too long to be shown completely")
        out.append(f"{tag} | {body}")
    return out


def review_entries(base: str, head: str, entries: Sequence[RawEntry], read_blob: Callable[[str], bytes]) -> ReviewedChange:
    """`read_blob(sha)` must return the raw object content (the caller's responsibility is only to fetch; it is verified here)."""
    if not entries:
        raise ChangeBlocked("the change is empty")
    if len(entries) > P.MAX_FILES:
        raise ChangeBlocked("too many changed files to review")
    files: list[FileChange] = []
    seen: set[str] = set()
    for e in entries:
        shown = P.clip(ascii(e.path), 80)
        if e.status != "M":
            raise ChangeBlocked(f"{shown}: only modifications of existing files are accepted (status {e.status!r})")
        if e.old_mode != REGULAR_MODE or e.new_mode != REGULAR_MODE:
            raise ChangeBlocked(f"{shown}: file mode/type change ({e.old_mode} -> {e.new_mode})")
        why = P.refuse_target(e.path)
        if why:
            raise ChangeBlocked(f"{shown}: {why}")
        if e.path in seen:
            raise ChangeBlocked(f"{shown}: reported twice")
        seen.add(e.path)
        raws = {}
        for label, sha in (("old", e.old_sha), ("new", e.new_sha)):
            data = read_blob(sha)
            if blob_sha1(data) != sha:
                raise ChangeBlocked(f"{shown}: {label} blob does not match its object id")
            raws[label] = data
        old, new = _decode(raws["old"], e.path), _decode(raws["new"], e.path)
        added = P.new_findings(old, new)
        if added:
            raise ChangeBlocked(f"{shown}: the change adds {added[0]} (manual review required)")
        files.append(FileChange(e.path, e.old_sha, e.new_sha, old, new))
    files.sort(key=lambda f: f.path)
    view: list[str] = []
    for f in files:
        view.extend(render_lines(f.old_text, f.new_text, f.path))
    if len(view) > MAX_VIEW_LINES:
        raise ChangeBlocked(f"the diff has {len(view)} lines; more than {MAX_VIEW_LINES} cannot be shown completely, so it cannot be approved")
    added_n = sum(1 for ln in view if ln.startswith("+ |"))
    removed_n = sum(1 for ln in view if ln.startswith("- |"))
    digest = change_digest(base, head, [(f.path, f.old_sha, f.new_sha) for f in files])
    return ReviewedChange(base, head, tuple(files), digest, tuple(view), f"{len(files)} file(s), +{added_n} -{removed_n}")


def approval_view(title: str, problem: str, change: ReviewedChange, stages: Sequence[tuple[str, bool, bool]], action: str) -> dict[str, str]:
    """Context for the confirmation dialog. Text written by a model or taken from logs (title, problem) appears ONLY as quoted single lines labelled as
    unverified; everything labelled JARVIS-checked is produced from this code's own data. The complete diff is part of the request."""
    checked = ", ".join(f"{n}={'ok' if ex and ok else 'NOT RUN' if not ex else 'FAILED'}" for n, ex, ok in stages) or "none"
    diff = "\n".join("  " + ln for ln in change.view)
    return {
        "[JARVIS] Aktion": action,
        "[JARVIS] Dateien": ", ".join(change.changed_files),
        "[JARVIS] Umfang": change.stat,
        "[JARVIS] Basis": change.base_commit[:12],
        "[JARVIS] Stand": change.head_commit[:12],
        "[JARVIS] Diff-Digest": change.diff_digest,
        "[JARVIS] Anzeige-Digest": change.view_digest,
        "[JARVIS] Pruefstufen": checked,
        "[unverifizierter Text] Titel": P.one_line(title, 120),
        "[unverifizierter Text] Problem": P.one_line(problem, 200),
        "[JARVIS] Vollstaendiger Diff (ESC-maskiert)": "\n" + diff,
    }
