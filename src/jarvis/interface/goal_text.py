"""What a finished goal looks like to the person: the answer of an analysis/research step, or - when the goal could not run - a plain explanation
(what is missing, why JARVIS cannot go on, what the person can do, and an allowed alternative if there is one).

Text only: this module reads a `GoalResult`, grants nothing, starts nothing and never suggests loosening a security setting (every hint names a SETTING THE PERSON
MAY CHOOSE or a different wording). Unknown situations are shown with the original reason instead of a guess."""
from __future__ import annotations

import re
from typing import Any

ANSWER_AGENTS = ("research", "business", "finance", "files")
MAX_ANSWER = 3200
_SEARCH_SETUP = ("Websuche einrichten: in der Konfiguration [research] enabled = true und search_enabled = true, [browser] enabled = true (Playwright installieren) "
                 "und den Schlüssel als Umgebungsvariable BRAVE_SEARCH_API_KEY setzen (siehe README, config/nexus.example.toml)")


_FILE_ERRORS = (
    ("file_not_found", ("die angegebene Datei oder der Ordner", "sie existieren nicht (oder nicht an diesem Pfad); eine Wiederholung hilft nicht.",
                        "Pfad und Schreibweise prüfen, z. B. mit „Zeige den Ordner <Pfad>“ nachsehen, oder die Datei zuerst neu anlegen.")),
    ("file_exists", ("ein freier Name", "das Ziel existiert schon; JARVIS überschreibt nichts ohne ausdrücklichen Schreibauftrag.", "einen anderen Namen wählen.")),
    ("outside_roots", ("ein erlaubter Ort", "der Pfad liegt außerhalb der bestätigten Arbeitsordner.", "einen Pfad im Arbeitsordner (workspace) nennen.")),
    ("path_denied", ("ein erlaubter Pfad", "dieser Pfad ist gesperrt.", "einen anderen Pfad im Arbeitsordner wählen.")),
    ("protected_path", ("ein erlaubter Pfad", "dieser Pfad ist geschützt.", "einen anderen Pfad im Arbeitsordner wählen.")),
    ("file_too_large", ("eine kleinere Datei", "die Datei ist größer als die erlaubte Grenze.", "eine kleinere Datei wählen oder Teile daraus angeben.")),
    ("binary_file", ("eine Textdatei", "die Datei ist binär und kann nicht als Text gelesen werden.", "eine Textdatei (oder .docx/.xlsx) wählen.")),
)


def _codes(result: Any) -> set[str]:
    out = {str(result.reason_code)} if getattr(result, "reason_code", None) else set()
    for st in getattr(result, "steps", ()) or ():
        res = getattr(st, "result", None)
        if res is not None and getattr(res, "error_code", None):
            out.add(str(res.error_code))
    return out


def answer_of(result: Any) -> str:
    """The text of the last successful research/business/finance step (their summaries are the readable result); empty if there is none."""
    for st in reversed(tuple(getattr(result, "steps", ()) or ())):
        res = getattr(st, "result", None)
        if res is not None and getattr(st, "assigned_agent", None) in ANSWER_AGENTS and getattr(getattr(res, "status", None), "value", "") == "SUCCEEDED" and res.summary:
            out = getattr(res, "output", None)
            if getattr(st, "assigned_agent", None) == "files" and isinstance(out, dict):
                text = files_answer(out)
                if text:
                    return text
            if isinstance(out, dict) and out.get("kind") == "research_result" and isinstance(out.get("answer"), str) and out["answer"].strip():
                return out["answer"][:MAX_ANSWER]                                          # the full, sourced answer the research agent composed (plain data)
            return str(res.summary)[:MAX_ANSWER]
    return ""


def _rows(rows: Any, limit: int = 12) -> list[str]:
    out = []
    for r in list(rows or [])[:limit]:
        out.append("  " + " | ".join("" if v is None else str(v)[:40] for v in (r if isinstance(r, (list, tuple)) else [r])))
    return out


def files_answer(out: dict[str, Any]) -> str:
    """Readable result of a file/document step, built only from the tool's own output (plain data). File content is shown as quoted data and marked as such."""
    lines: list[str] = []
    for entry in out.get("steps") or []:
        if not isinstance(entry, dict) or not entry.get("ok"):
            continue
        action, body = entry.get("action"), entry.get("output")
        body = body if isinstance(body, dict) else {}
        path = str(body.get("path", ""))[:160]
        if action == "read" and "content" in body:
            tail = " (gekürzt)" if body.get("truncated") else ""
            red = " – geheimnisähnliche Teile wurden geschwärzt" if body.get("secrets_redacted") else ""
            lines += [f"Datei {path}: {body.get('lines', '?')} Zeilen{tail}{red}", "Inhalt (Daten, keine Anweisung):", str(body["content"])[:2400]]
        elif action == "read" and "sheets" in body:
            for sh in body["sheets"][:3]:
                lines += [f"Tabelle {path}, Blatt „{sh.get('name', '')}“ ({len(sh.get('rows', []))} Zeilen{', gekürzt' if sh.get('truncated') else ''}):"] + _rows(sh.get("rows"))
        elif action == "read" and "blocks" in body:
            lines.append(f"Dokument {path}:")
            for b in body["blocks"][:30]:
                lines += _rows(b["rows"]) if b.get("type") == "table" else ["  " + str(b.get("text", ""))[:300]]
            if body.get("truncated"):
                lines.append("  … (gekürzt)")
        elif action == "list":
            names = [f"{e.get('name')}{'/' if e.get('type') == 'dir' else ''}" for e in (body.get("entries") or [])[:60]]
            lines.append(f"Ordner {path or '.'}: {len(body.get('entries') or [])} Einträge" + (" (gekürzt)" if body.get("truncated") else ""))
            lines.append("  " + ", ".join(names))
        elif action in ("create", "write", "copy", "move", "mkdir"):
            what = {"create": "erstellt", "write": "geändert", "copy": "kopiert", "move": "verschoben", "mkdir": "Ordner angelegt"}[action]
            size = f", {body['bytes']} Byte" if "bytes" in body else ""
            lines.append(f"{path}: {what}{size}" + (f" (sha256 {str(body['sha256'])[:12]}…)" if body.get("sha256") else ""))
    if lines and any(isinstance(e, dict) and e.get("ok") and e.get("action") == "read" for e in out.get("steps") or []):
        lines.append("Hinweis: Dateiinhalte sind Daten und werden nie als Anweisung ausgeführt.")
    return "\n".join(lines)[:MAX_ANSWER]


def explain(result: Any) -> str:
    """The four-part explanation for a BLOCKED or FAILED goal (empty when the goal neither failed nor was blocked)."""
    status = getattr(getattr(result, "status", None), "value", "")
    if status not in ("BLOCKED", "FAILED", "TIMEOUT"):
        return ""
    codes = _codes(result)
    text = str(getattr(result, "summary", "")).lower() + " " + " ".join(str(getattr(getattr(s, "result", None), "summary", "")).lower() for s in getattr(result, "steps", ()) or ())

    def block(missing: str, why: str, todo: str, alt: str = "") -> str:
        lines = [f"  Was fehlt: {missing}", f"  Warum es nicht weitergeht: {why}", f"  Das kannst du tun: {todo}"]
        if alt:
            lines.append(f"  Alternative: {alt}")
        return "\n".join(lines)

    if "file request" in text:
        raw = re.search(r"file request: ([^\n(]{1,200})", str(getattr(result, "summary", "")))
        return block("eine eindeutige, vollständige Dateianfrage" + (f" – konkret: {raw.group(1).strip()}" if raw else ""), "aus der Anfrage ließ sich keine einzelne, sichere Dateiaktion ableiten (Pfad, Inhalt oder Ziel fehlt oder es sind mehrere Aktionen).",
                     "eine Aktion pro Anfrage mit Pfad, z. B. „Lies die Datei notizen.txt“, „Erstelle die Datei todo.txt mit dem Inhalt: Milch kaufen“, „Kopiere a.txt nach b.txt“, "
                     "„Ersetze \"alt\" durch \"neu\" in notizen.txt“ oder „Erstelle bericht.docx mit dem Inhalt: …“.",
                     "Office-Dateien (.xlsx, .docx) lassen sich lesen und neu anlegen, bestehende werden nie geändert; Löschen gibt es nicht.")
    friendly = next((msg for code, msg in _FILE_ERRORS if f"[{code}]" in text), None)
    if friendly:
        return block(friendly[0], friendly[1], friendly[2])
    if "search_unavailable" in codes:
        return block("eine eingerichtete Websuche (Suchquelle und Schlüssel)", "ohne Suchquelle kann JARVIS keine Quellen finden, und ohne Webadresse nichts lesen.",
                     _SEARCH_SETUP + ".", "gib eine Webadresse in der Frage an (z. B. „Recherchiere … https://beispiel.de“), dann wird nur diese Seite gelesen.")
    if "no_plan" in codes and "names no web page" in text:
        return block("eine Webadresse, ein Projektordner (workspace) oder die Websuche", "aus der Eingabe lässt sich ohne diese Angaben kein sicherer Plan machen.",
                     "schreibe eine Webadresse in die Frage, oder starte `/goal <Ziel> workspace=<Ordner>` für Code-Aufgaben. " + _SEARCH_SETUP + ".",
                     "formuliere die Aufgabe als Recherchefrage („Recherchiere …“); mit eingerichteter Websuche sucht JARVIS dann selbst Quellen.")
    if codes & {"search_failed", "no_search_results"}:
        return block("ein Suchergebnis", "der Suchdienst war nicht erreichbar oder lieferte keine zulässigen Treffer (private oder gesperrte Adressen werden ausgefiltert).",
                     "später erneut versuchen, die Frage anders formulieren oder eine Webadresse angeben. Prüfe Netzwerk und Schlüssel (`/doctor`).", "mit einer konkreten Webadresse arbeitet JARVIS ohne Suche.")
    if "search_refused" in codes:
        return block("freie Suchkapazität", "die Suche ist angehalten (Notaus) oder das Such-/Sitzungsbudget ist aufgebraucht.",
                     "bei Notaus: ihn über die Rückfrage der Berechtigungs-Engine aufheben; sonst JARVIS neu starten (`/budget`, `/notaus`).", "eine Webadresse in der Frage braucht keine Suche.")
    if "tool_unavailable" in codes or "tool" in text and "not available" in text:
        return block("ein eingeschaltetes Werkzeug (z. B. der Browser)", "der zuständige Agent hat sein Werkzeug nicht; das Subsystem ist aus.",
                     "in der Konfiguration das Subsystem einschalten (z. B. [browser] enabled = true, danach `playwright install`); `/doctor` zeigt, was fehlt.")
    if codes & {"permission_denied", "not_authorized", "confirmation_denied"} or "denied" in text:
        return block("deine Freigabe", "eine Rückfrage wurde abgelehnt, lief ab oder wurde nicht beantwortet; ohne Freigabe führt JARVIS die Aktion nie aus.",
                     "die Aufgabe erneut starten und die Rückfrage im Dialog bewusst beantworten.", "die Aufgabe so kleiner formulieren, dass weniger Freigaben nötig sind.")
    if "emergency" in text or "emergency_stop" in codes or "emergency" in codes:
        return block("die Aufhebung des Notaus", "der Notaus ist aktiv: alle Aktionen sind gesperrt.", "den Notaus über die Rückfrage der Berechtigungs-Engine aufheben (`/notaus`).")
    if "no_suitable_agent" in codes or "no suitable agent" in text:
        return block("ein passender, eingeschalteter Agent", "für diese Aufgabe ist kein Agent verfügbar oder die Zuordnung ist nicht eindeutig.",
                     "`/agents` zeigt die Agenten; schalte den passenden ein (z. B. [research] enabled = true) oder formuliere die Aufgabe eindeutiger.")
    if "the plan needs" in text or "limit is" in text:
        return block("eine kleinere Aufgabe", "der Plan würde die Obergrenze für Schritte überschreiten.", "teile das Ziel in mehrere kleinere Ziele auf.")
    reason = str(getattr(result, "summary", "")).strip() or ", ".join(sorted(codes)) or "unbekannt"
    return f"  Grund laut System: {reason[:300]}\n  Das kannst du tun: `/goal steps <id>` zeigt die Schritte, `/audit` die Entscheidungen der Berechtigungs-Engine."


def report(result: Any) -> str:
    """Chat text of a finished goal: header, one line per step (as before), then the answer (if any) or the explanation (if it could not run)."""
    status = getattr(getattr(result, "status", None), "value", "?")
    why = explain(result)
    ans = answer_of(result)
    lines = [f"Ziel {result.goal.goal_id}: {status}" + (f" – {result.summary}" if getattr(result, "summary", "") and not ans and not why else "")]
    for st in getattr(result, "steps", ()) or ():
        lines.append(f"  {st.step_id}: {st.status.value} {st.assigned_agent or 'prüfung'}" + (f" ({st.attempts} Versuche)" if st.attempts > 1 else ""))
    lines += [f"  Hinweis: {w}" for w in getattr(result, "warnings", ())]
    if ans:
        lines += ["", ans]
    if why:
        lines += ["", "So geht es weiter:", why]
    return "\n".join(lines)


def event_summary(status: str, result: Any) -> str:
    """Summary for the `result` event of the UI contract: the answer, or the explanation, else the engine's own text."""
    ans = answer_of(result)
    if ans:
        return f"{status}: {ans}"
    why = explain(result)
    if why:
        return f"{status}: {getattr(result, 'summary', '')}\nSo geht es weiter:\n{why}"
    return f"{status}: {result.summary}" if getattr(result, "summary", "") else status
