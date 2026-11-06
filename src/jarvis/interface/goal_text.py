"""What a finished goal looks like to the person: the answer of an analysis/research step, or - when the goal could not run - a plain explanation
(what is missing, why JARVIS cannot go on, what the person can do, and an allowed alternative if there is one).

Text only: this module reads a `GoalResult`, grants nothing, starts nothing and never suggests loosening a security setting (every hint names a SETTING THE PERSON
MAY CHOOSE or a different wording). Unknown situations are shown with the original reason instead of a guess."""
from __future__ import annotations

from typing import Any

ANSWER_AGENTS = ("research", "business", "finance")
MAX_ANSWER = 3200
_SEARCH_SETUP = ("Websuche einrichten: in der Konfiguration [research] enabled = true und search_enabled = true, [browser] enabled = true (Playwright installieren) "
                 "und den Schlüssel als Umgebungsvariable BRAVE_SEARCH_API_KEY setzen (siehe README, config/nexus.example.toml)")


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
            if isinstance(out, dict) and out.get("kind") == "research_result" and isinstance(out.get("answer"), str) and out["answer"].strip():
                return out["answer"][:MAX_ANSWER]                                          # the full, sourced answer the research agent composed (plain data)
            return str(res.summary)[:MAX_ANSWER]
    return ""


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
