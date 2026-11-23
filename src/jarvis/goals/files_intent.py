"""Natural-language file requests -> ONE structured step (no model, no network, no state).

Recognised, deliberately small set (German and English): read a file, list a folder, create a file with given content, create a folder, copy, move and replace a
text in a file. The path must be named in the request (quoted, or a token with a file extension / separator); the content must be given in the request. Nothing is
guessed: a request that fits more than one kind, names no path or lacks required content gives `FileIntentError` with the reason, so the person gets a plain explanation.
The result is data for the planner: {"tool", "action", ...args}. Whether the action is allowed is decided later by the permission engine, for the exact path."""
from __future__ import annotations

import re
from typing import Any

OFFICE_EXTS = (".xlsx", ".docx")
MAX_CONTENT = 20_000
_Q = r"""(?:"([^"\n]{1,500})"|„([^“”"\n]{1,500})[“”"]|'([^'\n]{1,500})'|‚([^‘’'\n]{1,500})[‘’'])"""
_TOKEN = r"""((?:[A-Za-z]:)?[\w.\-\\/~]*\w\.[A-Za-z0-9]{1,5})"""
_PATH = rf"(?:{_Q}|{_TOKEN})"
_DIRTOKEN = r"""((?:[A-Za-z]:)?[\w.\-\\/~]+)"""


class FileIntentError(ValueError):
    """The request looks like a file request but cannot be turned into a safe, complete step."""


def _q(m: re.Match[str], first: int, width: int = 4) -> str | None:
    for i in range(first, first + width):
        if m.group(i):
            return m.group(i)
    return None


def _path_from(m: re.Match[str], first: int) -> str | None:
    return _q(m, first) or m.group(first + 4)


_CREATE = re.compile(rf"\b(?:erstelle|erstell|lege|leg|schreibe|speichere|create|write|save|make)\b.*?{_PATH}\s*(?:,\s*)?(?:mit\s+(?:dem\s+)?(?:inhalt|text)|die\s+(?:den\s+)?(?:inhalt|text)|enthält|enthaelt|containing|with\s+(?:the\s+)?(?:content|text))\s*[:\-]?\s*(?P<content>.+)$",
                     re.IGNORECASE | re.DOTALL)
_REPLACE = re.compile(rf"\b(?:ersetze|replace)\s+{_Q}\s+(?:durch|mit|by|with)\s+{_Q}\s+(?:in|within)\s+(?:der\s+datei\s+|datei\s+|the\s+file\s+|file\s+)?{_PATH}", re.IGNORECASE)
_READ = re.compile(rf"\b(?:lies|lese|zeige|zeig|öffne|oeffne|read|show|display|open|was\s+steht\s+in)\b.*?{_PATH}", re.IGNORECASE)
_LIST = re.compile(rf"\b(?:liste|zeige|zeig|list|show)\b.*?\b(?:ordner|verzeichnis|folder|directory|dateien\s+in|files\s+in)\s+(?:(?:{_Q})|{_DIRTOKEN})", re.IGNORECASE)
_NAMED = r"(?:(?:namens|genannt|named|called|mit\s+dem\s+namen|with\s+the\s+name)\s+)?"        # "Ordner namens Projekte", "folder called Reports"
_MKDIR = re.compile(rf"\b(?:erstelle|lege|create|make)\b.*?\b(?:ordner|verzeichnis|folder|directory)\s+{_NAMED}(?:(?:{_Q})|{_DIRTOKEN})", re.IGNORECASE)
_MKDIR_BARE = re.compile(r"\b(?:erstelle|lege|create|make)\b[^.?!\n]*\b(?:ordner|verzeichnis|folder|directory)\s*[.!]?\s*$", re.IGNORECASE)
# A well-known place named instead of a path ("auf dem Desktop"): JARVIS never guesses what it resolves to; the person names the full path.
_PLACE = re.compile(r"\b(?:(?:auf|on)\s+(?:dem|the|meinem|my)\s+desktop|(?:im|in|in\s+den|in\s+meinen)\s+(?:dokumente\w*|downloads?|bilder\w*)|(?:in|on)\s+(?:the|my)\s+(?:documents|downloads|pictures))\b", re.IGNORECASE)
_CREATE_VERB = re.compile(r"^(?:(?!inhalt|content|text\b).)*\b(?:erstelle|erstell|create)\b(?:(?!inhalt|content|text\b).)*$", re.IGNORECASE | re.DOTALL)   # a plain "create" wish only; wording about content is left to the other rules
_NAMED_FILE = re.compile(r"((?:[A-Za-z]:)?[\w.\-\\/~]*\w\.(?:txt|md|csv|json|docx|xlsx))\b", re.IGNORECASE)         # a document name WITH a known extension, but no content was given
_NOT_A_NAME =frozenset({"auf", "in", "im", "an", "am", "unter", "bei", "von", "vom", "zu", "zum", "nach", "mit", "für", "fuer", "namens", "genannt", "dem", "den", "der", "die", "das",
                         "ein", "eine", "einen", "neuen", "neue", "bitte", "und", "on", "at", "under", "named", "called", "with", "for", "the", "please", "and"})
_COPYMOVE =re.compile(rf"\b(?P<verb>kopiere|verschiebe|copy|move)\s+(?:die\s+datei\s+|datei\s+|the\s+file\s+|file\s+)?{_PATH}\s+(?:nach|zu|to|into)\s+{_PATH}", re.IGNORECASE)
_NEG_ANALYSIS = re.compile(r"\b(?:recherchier|research|marktanalyse|businessplan)\w*", re.IGNORECASE)
# A request for an explanation or instructions ABOUT a file task ("Erstelle eine Anleitung, wie ich einen Ordner auf dem Desktop erstelle") asks for TEXT, not for the action.
_NEG_HOWTO = re.compile(r"\b(?:anleitung|anleitungen|tutorial|erkl[aä]r\w*|erl[aä]uter\w*|how[\s-]?to|instructions?|step[\s-]by[\s-]step|schritt[\s-]f[uü]r[\s-]schritt)\b"
                        r"|\bwie\s+(?:\w+\s+)?(?:ich|man)\b|\bwie\s+(?:kann|muss|soll)\s+ich\b|\bhow\s+(?:do|can|should)\s+i\b", re.IGNORECASE)


def _tool_for(path: str) -> str:
    return "office" if path.lower().endswith(OFFICE_EXTS) else "files"


def parse_file_goal(text: str) -> dict[str, Any] | None:
    """The one step the request asks for, or None if it is not a file request. Raises FileIntentError for an incomplete or ambiguous file request."""
    if not isinstance(text, str) or not text.strip() or _NEG_ANALYSIS.search(text) or _NEG_HOWTO.search(text):
        return None
    t = " ".join(text.split()) if "\n" not in text else text.strip()
    found: list[dict[str, Any]] = []
    m = _COPYMOVE.search(t)
    if m:
        src, dst = _path_from(m, 2), _path_from(m, 7)
        if not src or not dst:
            raise FileIntentError("Quelle und Ziel müssen genannt werden")
        found.append({"tool": "files", "action": "copy" if m.group("verb").lower() in ("kopiere", "copy") else "move", "path": src, "destination": dst})
    m = _REPLACE.search(t)
    if m:
        old, new, path = _q(m, 1), _q(m, 5), _path_from(m, 9)
        if not old or new is None or not path:
            raise FileIntentError("Alter Text, neuer Text und Datei müssen in Anführungszeichen bzw. als Dateiname genannt werden")
        if _tool_for(path) == "office":
            raise FileIntentError("Bestehende Office-Dateien werden nie geändert (nur lesen oder neu anlegen)")
        found.append({"tool": "files", "action": "replace", "path": path, "old_text": old, "new_text": new})
    m = _CREATE.search(t)
    if m:
        path, content = _path_from(m, 1), m.group("content").strip()
        if len(content) >= 2 and content[0] in "\"„'‚" and content[-1] in "\"“”'‘’":
            content = content[1:-1]
        if not path or not content:
            raise FileIntentError("Zum Erstellen einer Datei müssen Name und Inhalt genannt werden („… mit dem Inhalt: …“)")
        if len(content) > MAX_CONTENT:
            raise FileIntentError(f"Der Inhalt ist länger als {MAX_CONTENT} Zeichen")
        if _MKDIR.search(t):                                    # "Erstelle einen Ordner X und lege darin die Datei a.txt ... an": two actions, one request is refused (never half done)
            raise FileIntentError("Die Anfrage enthält mehrere Dateiaktionen (Ordner und Datei); bitte einzeln stellen")
        found.append({"tool": _tool_for(path), "action": "create", "path": path, "content": content})
    if not found and _CREATE_VERB.search(t) and (named := _NAMED_FILE.search(t)):
        raise FileIntentError(f"Zum Erstellen von {named.group(1)} fehlt der Inhalt („… mit dem Inhalt: …“); ohne Inhalt legt JARVIS keine Datei an")
    if not found:
        m = _MKDIR.search(t)
        if m:
            name = _q(m, 1)
            if name is None:
                name = m.group(5)
                if name.lower() in _NOT_A_NAME:                 # "Ordner auf dem Desktop": a preposition/article is no folder name -> ask for the real one
                    raise FileIntentError("Es wurde kein Ordnername genannt (z. B. „Erstelle den Ordner Archiv“ oder mit vollem Pfad in Anführungszeichen)")
            found.append({"tool": "files", "action": "mkdir", "path": name})
    if not found and _MKDIR_BARE.search(t):
        raise FileIntentError("Es wurde kein Ordnername genannt (z. B. „Erstelle den Ordner Archiv“ oder mit vollem Pfad in Anführungszeichen)")
    if not found:
        m = _LIST.search(t)
        if m:
            found.append({"tool": "files", "action": "list", "path": _q(m, 1) or m.group(5)})
    if not found:
        m = _READ.search(t)
        if m:
            path = _path_from(m, 1)
            if path:
                found.append({"tool": _tool_for(path), "action": "read", "path": path})
    if not found:
        return None
    if len(found) > 1:
        raise FileIntentError("Die Anfrage enthält mehrere Dateiaktionen; bitte einzeln stellen")
    step = found[0]
    if not step.get("path"):
        raise FileIntentError("Es wurde kein Pfad genannt")
    if step["action"] != "read" and _PLACE.search(t) and not re.search(r"[\\/:]", step["path"]):
        raise FileIntentError("Orte wie „Desktop“ oder „Dokumente“ werden nicht erraten: nenne den vollständigen Pfad in Anführungszeichen "
                              "(z. B. „C:\\Users\\Name\\Desktop\\Projekte“)")
    if step["action"] != "read":
        other = _READ.search(t)
        if other and (_path_from(other, 1) or "") not in (step["path"], step.get("destination", "")):
            raise FileIntentError("Die Anfrage enthält mehrere Dateiaktionen; bitte einzeln stellen")
    return step
