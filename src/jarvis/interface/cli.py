"""Command-line test interface (`jarvis`)."""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Any, Callable, Sequence

from jarvis import __version__
from jarvis.bootstrap import build_core, build_voice_session
from jarvis.config import load_settings
from jarvis.config import Settings
from jarvis.core import JarvisCore
from jarvis.core.core import format_entries
from jarvis.errors import JarvisError, VoiceError
from jarvis.permissions import CliConfirmation

HELP = """Befehle:
  /plan <ziel>   Plan für ein Ziel erstellen
  /tasks         Offene Tasks anzeigen
  /tools         Registrierte Tools anzeigen
  /reset         Gesprächskontext löschen
  /remember <t>  Etwas dauerhaft merken
  /memory [q]    Erinnerungen suchen / neueste anzeigen
  /forget <id>   Erinnerung löschen
  /run <tool> k=v  Tool über die Berechtigungsprüfung ausführen
  /permissions   Sicherheitsmodus, erlaubte Verzeichnisse, Regeln, Sitzungsfreigaben
  /audit [n]     Letzte Sicherheitsereignisse
  /revoke        Sitzungsfreigaben widerrufen
  /notaus        NOTAUS: sperrt sofort alle Aktionen/Ziele/Tool-Aufrufe und stoppt Komponenten (reset = aufheben, nur mit ausdrücklicher Bestätigung; status)
  /budget        Sitzungsbudget (Tool-Aufrufe/Laufzeit): Verbrauch anzeigen (nur lesend; kein Zurücksetzen, keine Erhöhung)
  /computer      Status der Computersteuerung (stop = Notaus, resume = fortsetzen)
  /browser       Browser-Agent: Status | start | stop | pages | halt (Notaus) | resume (sonst: /run browser action=...)
  /coding        Coding-Agent: Status | halt (Notaus) | resume | stop (Sitzung beenden) (sonst: /run coding action=...)
  /agents        Agenten und ihr Status
  /agent <id>    Details eines Agenten | halt <task_id> (abbrechen) | plan <Text> | enable|disable|reset <id>
  /agenttasks    Aktive und letzte Agent-Tasks
  /goals         Ziele und ihr Status
  /research      Research-Agent: Status (liest öffentliche Seiten über den Browser; Aufruf: /run research action=check_url url=…)
  /business      Business-Agent: Status (Analysen/Entwürfe, sendet nichts; /run business action=break_even …)
  /finance       Finance-Agent: Status (nur Analyse und Paper-Trading, keine Orders; /run finance action=risk_reward …)
  /repair <Ziel> workspace="…" [tests=… runner=… candidates='[…]'] | status [id] | attempts <id> | cancel <id>   Test/Reparatur im Workspace
  /improve       Selbstverbesserung (nur Vorschläge; Code wird nicht vorbereitet/getestet/aktiviert): analyze [llm] | list | show <id> | propose "<Titel>" "<Problem>" | reject <id>
  /goal <Ziel>   Ziel ausführen (optional: url=… workspace=… runner=… read_paths=a,b) | status|steps|cancel <id>
  /voice         Sprachmodus starten (zurück mit „exit“)
  /help          Diese Hilfe
  /exit          Beenden"""

PROMPT = "jarvis> "


def run_command(core: JarvisCore, line: str, settings: Settings | None = None,
                output_fn: Callable[[str], None] = print, input_fn: Callable[[str], str] = input) -> str | None:
    """Return output text, or None to quit."""
    cmd, _, arg = line.partition(" ")
    arg = arg.strip()
    if cmd in ("/exit", "/quit"):
        return None
    if cmd == "/help":
        return HELP
    if cmd == "/tools":
        return "\n".join(f"  {t['name']}: {t['description']}" for t in core.tools.describe_all())
    if cmd == "/tasks":
        open_tasks = core.tasks.open_tasks()
        if not open_tasks:
            return "Keine offenen Tasks."
        return "\n".join(f"  [{t.id}] {t.status.value:<9} {t.description}" for t in open_tasks)
    if cmd == "/reset":
        core.context.clear()
        return "Kontext gelöscht."
    if cmd == "/run":
        return _run_tool(core, arg)
    if cmd == "/computer":
        return _computer(core, arg)
    if cmd == "/browser":
        return _browser(core, arg)
    if cmd == "/coding":
        return _coding(core, arg)
    if cmd in ("/agents", "/agent", "/agenttasks"):
        return _agents(core, cmd, arg)
    if cmd in ("/goals", "/goal"):
        return _goals(core, cmd, arg)
    if cmd == "/repair":
        return _repair(core, arg)
    if cmd == "/improve":
        return _improve(core, arg)
    if cmd in ("/research", "/business", "/finance"):
        return _analysis_status(core, cmd[1:], arg)
    if cmd == "/permissions":
        return _describe_permissions(core)
    if cmd == "/audit":
        return _tail_audit(core, arg)
    if cmd in ("/notaus", "/emergency"):
        return _emergency(core, arg)
    if cmd == "/budget":
        budget = getattr(core.permissions, "budget", None)
        return budget.summary() if budget is not None else "Kein Sitzungsbudget aktiv (budget.enabled = false). Es lässt sich im laufenden Betrieb nicht einschalten."
    if cmd == "/revoke":
        return f"{core.permissions.revoke_session_grants('revoked by user')} Sitzungsfreigabe(n) widerrufen."
    if cmd == "/remember":
        if not arg:
            return "Verwendung: /remember <text>"
        r = core.handle("Merk dir: " + arg)
        return r.text
    if cmd == "/memory":
        found = core.recall(arg)
        return format_entries(found) if found else "Keine Erinnerungen gefunden."
    if cmd == "/forget":
        if not arg:
            return "Verwendung: /forget <id>"
        return f"Erinnerung {arg} gelöscht." if core.forget(arg) else f"Keine Erinnerung mit der ID {arg}."
    if cmd == "/voice":
        return _voice(core, settings, output_fn, input_fn)
    if cmd == "/plan":
        return core.plan(arg).text if arg else "Verwendung: /plan <ziel>"
    return f"Unbekannter Befehl: {cmd}. /help zeigt alle Befehle."


def repl(core: JarvisCore, input_fn: Callable[[str], str] | None = None,
         output_fn: Callable[[str], None] | None = None, settings: Settings | None = None,
         start_voice: bool = False) -> None:
    input_fn, output_fn = input_fn or input, output_fn or print
    if isinstance(core.permissions.confirmation, CliConfirmation):  # confirmations use this REPL's terminal
        core.permissions.confirmation.bind_io(input_fn, output_fn)
    output_fn(f"JARVIS {__version__} – /help für Befehle, /exit zum Beenden.")
    if start_voice:
        output_fn(_voice(core, settings, output_fn, input_fn))
    while True:
        try:
            line = input_fn(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            return
        if not line:
            continue
        try:
            if line.startswith("/"):
                out = run_command(core, line, settings, output_fn, input_fn)
                if out is None:
                    output_fn("Bis bald.")
                    return
            else:
                out = core.handle(line).text
        except JarvisError as exc:
            out = f"Fehler: {exc}"
        output_fn(out)


_WIN_TOKEN = re.compile(r'(?:[^\s"\']|"[^"]*"|\'[^\']*\'|["\'])+')


def _split_tool_args(arg: str, windows: bool | None = None) -> list[str]:
    """Split a /run line. POSIX rules would eat the backslashes of Windows paths, so use non-POSIX mode there."""
    if windows is None:
        windows = sys.platform == "win32"
    if not windows:
        return shlex.split(arg)
    parts = []
    for m in _WIN_TOKEN.finditer(arg):
        tok = m.group(0)
        if tok.count('"') % 2 or tok.count("'") % 2:
            raise ValueError("No closing quotation")
        parts.append(re.sub(r'"([^"]*)"|\'([^\']*)\'', lambda q: q.group(1) if q.group(1) is not None else q.group(2), tok))
    return parts


def _run_tool(core: JarvisCore, arg: str) -> str:
    try:
        parts = _split_tool_args(arg)
    except ValueError as exc:
        return f"Ungültige Eingabe: {exc}"
    if not parts:
        return "Verwendung: /run <tool> key=value ..."
    kwargs: dict[str, str] = {}
    for item in parts[1:]:
        key, sep, value = item.partition("=")
        if not sep or not key:
            return f"Ungültiges Argument {item!r}; erwartet key=value"
        kwargs[key] = value
    result = core.tools.execute(parts[0], **kwargs)  # permission engine decides; confirmation is asked via the CLI
    return f"OK: {result.output}" if result.success else f"Nicht ausgeführt: {result.error}"


def _computer(core: JarvisCore, arg: str) -> str:
    """Status and emergency stop of the optional computer-control subsystem (duck-typed: the CLI imports nothing from it)."""
    sub = core.subsystems.get("computer")
    if sub is None:
        return "Computersteuerung: nicht konfiguriert."
    if arg in ("stop", "halt"):
        return "Computersteuerung angehalten (Notaus). /computer resume setzt sie fort." if sub.halt() \
            else "Computersteuerung ist nicht aktiv."
    if arg == "resume":
        return "Computersteuerung fortgesetzt." if sub.resume() else "Computersteuerung ist nicht aktiv."
    d = sub.describe()
    names = {"enabled": "aktiv", "disabled": "deaktiviert", "unavailable": "nicht verfügbar", "halted": "ANGEHALTEN"}
    lines = [f"Computersteuerung: {names.get(d['status'], d['status'])}" + (f" – {d['reason']}" if d.get("reason") else "")]
    if d["status"] in ("enabled", "halted"):
        lines.append(f"Backend: {d['backend']}   Fähigkeiten: {', '.join(d['capabilities'])}")
        lines.append("Werkzeuge: " + ", ".join(d["tools"]) + "  (Aufruf: /run <werkzeug> key=value ...)")
        lines.append("Anwendungen: " + (", ".join(d["apps"]) or "keine konfiguriert (computer.apps)"))
        lines.append("Gespeicherte Screenshots: " + (", ".join(d["stored_screenshots"]) or "keine"))
    elif d["status"] == "disabled":
        lines.append("Aktivieren: computer.enabled = true bzw. JARVIS_COMPUTER_ENABLED=true (benötigt pip install -e \".[computer]\")")
    return "\n".join(lines)


def _browser(core: JarvisCore, arg: str) -> str:
    """Status / emergency stop of the optional browser agent. Real actions are ordinary tool calls (/run browser ...) and
    therefore go through the permission engine like everything else; this helper adds no second command path."""
    sub = core.subsystems.get("browser")
    if sub is None:
        return "Browser-Agent: nicht konfiguriert."
    if arg == "halt":
        return "Browser-Agent angehalten (Notaus). /browser resume setzt ihn fort." if sub.halt() else "Browser-Agent ist nicht aktiv."
    if arg == "resume":
        return "Browser-Agent fortgesetzt." if sub.resume() else "Browser-Agent ist nicht aktiv."
    d = sub.describe()
    if arg in ("start", "stop", "pages", "status") and d["status"] in ("enabled", "halted"):
        return _run_tool(core, f"browser action={arg}")
    names = {"enabled": "aktiv", "disabled": "deaktiviert", "unavailable": "nicht verfügbar", "halted": "ANGEHALTEN"}
    lines = [f"Browser-Agent: {names.get(d['status'], d['status'])}" + (f" – {d['reason']}" if d.get("reason") else "")]
    if d["status"] in ("enabled", "halted"):
        lines.append(f"Provider: {d['provider']}   Sitzung: {d['session'] or 'keine'}   Seiten: {d['pages']}   Aktionen: {d['actions_used']}")
        lines.append("Aufruf: /run browser action=start | goto url=https://… | text | links | find query=… | click element=e3 ...")
    elif d["status"] == "disabled":
        lines.append("Aktivieren: browser.enabled = true bzw. JARVIS_BROWSER_ENABLED=true (benötigt pip install -e \".[browser]\")")
    return "\n".join(lines)


def _coding(core: JarvisCore, arg: str) -> str:
    """Status and the user's controls (halt / resume / stop) of the optional coding agent. Real work is done by ordinary tool calls
    (/run coding ...) and therefore goes through the permission engine; `halt`/`resume`/`stop` exist ONLY here, for the user."""
    sub = core.subsystems.get("coding")
    if sub is None:
        return "Coding Agent: nicht konfiguriert."
    if arg == "halt":
        return "Coding Agent angehalten (Notaus). /coding resume setzt ihn fort." if sub.halt() else "Coding Agent ist nicht aktiv."
    if arg == "resume":
        return "Coding Agent fortgesetzt." if sub.resume() else "Coding Agent ist nicht aktiv."
    if arg == "stop":
        if not sub.available:
            return "Coding Agent ist nicht aktiv."
        return "Coding-Sitzung beendet (Dateien bleiben unverändert)." if sub.stop() else "Keine laufende Coding-Sitzung."
    d = sub.describe()
    names = {"enabled": "aktiv", "disabled": "deaktiviert", "unavailable": "nicht verfügbar", "halted": "ANGEHALTEN"}
    lines = [f"Coding Agent: {names.get(d['status'], d['status'])}" + (f" – {d['reason']}" if d.get("reason") else "")]
    if d["status"] in ("enabled", "halted"):
        s = d.get("session")
        if s is None:
            lines.append("Keine Sitzung. Start: /run coding action=start workspace=<Verzeichnis>   (erlaubte Wurzeln: " + ", ".join(d["roots"]) + ")")
        else:
            lines += [f"Workspace: {s['root']}" + ("   [JARVIS-Repository: strenge Regeln]" if s["is_jarvis_workspace"] else ""),
                      f"Session: {s['id']}", f"Status: {s['status']}" + (f" ({s['failure']})" if s.get("failure") else ""),
                      f"Actions: {s['actions']}/{d['limits']['max_actions_per_session'] or '∞'}", f"Changed files: {len(s['changed_files'])}",
                      f"Tests: {s['tests_run']}"]
        lines.append("Aufruf: /run coding action=info|list|read|search|write|delete|test|git ...")
    elif d["status"] == "disabled":
        lines.append("Aktivieren: coding.enabled = true bzw. JARVIS_CODING_ENABLED=true")
    return "\n".join(lines)


def _agents(core: JarvisCore, cmd: str, arg: str) -> str:
    """Overview and controls of the multi-agent layer (duck-typed). Agents act only through the permission-checked tools; these commands
    only show state, cancel tasks and switch agents on and off."""
    sub = core.subsystems.get("agents")
    if sub is None:
        return "Multi-Agent: nicht konfiguriert."
    if sub.orchestrator is None:
        return f"Multi-Agent: deaktiviert – {sub.reason}\nAktivieren: agents.enabled = true bzw. JARVIS_AGENTS_ENABLED=true"
    orch, reg = sub.orchestrator, sub.registry
    from jarvis.agents.errors import AgentError
    if cmd == "/agents":
        lines = [f"Agenten (aktiv {orch.active_agents}/{orch.max_concurrent}, wartend {orch.queued}):"]
        for a in reg.list():
            lines.append(f"  {a.id:<10} {a.status.value:<10} {a.name}" + (f"  [{a.state.reason}]" if a.state.reason else ""))
        return "\n".join(lines)
    if cmd == "/agenttasks":
        results = orch.list(limit=15)
        if not results:
            return "Keine Agent-Tasks."
        out = []
        for r in results:
            d = orch.describe(r.task_id)
            flags = (" (Abbruch angefordert)" if d["cancel_requested"] and not r.is_terminal else "") + (" (Arbeit läuft noch)" if d["still_running"] else "")
            out.append(f"  {r.task_id}  {r.status.value:<9} {r.agent_id or '-':<9} {d['objective'][:50]}" + (f" – {r.error_code}" if r.error_code else "") + flags)
        return "\n".join(out)
    word, _, rest = arg.partition(" ")
    rest = rest.strip()
    try:
        if word == "halt":
            rep = orch.cancel(rest)
            return f"{rep.task_id}: {rep.message} ({rep.status.value})"
        if word == "plan":
            sel = sub.select(rest)
            return (f"Geeignet: {sel.agent_id} ({', '.join(sorted(sel.capabilities))}) – {sel.reason}" if sel.found
                    else f"Kein Agent gewählt: {sel.reason}")
        if word in ("enable", "disable", "reset"):
            status = orch.reset_agent(rest) if word == "reset" else orch.set_enabled(rest, word == "enable")
            return f"{rest}: {status.value}"
        if not arg:
            return "Verwendung: /agent <id> | halt <task_id> | plan <text> | enable|disable|reset <id>"
        a = reg.get(arg)
    except AgentError as exc:
        return f"Nicht möglich: {exc}"
    d = a.describe()
    return "\n".join([f"{d['id']}: {d['name']} – {d['status']}" + (f" ({d['reason']})" if d["reason"] else ""), f"  {d['description']}",
                      "  Fähigkeiten: " + ", ".join(d["capabilities"]), "  Werkzeuge: " + (", ".join(d["tools"]) or "keine"),
                      f"  Abbruch unterstützt: {'ja' if d['supports_cancellation'] else 'nein'}"])


_GOAL_OPT = re.compile(r"(?:^|\s)(url|workspace|runner|read_paths)=(\"[^\"]*\"|\S+)")


def _fmt_goal(g: Any) -> str:
    return f"{g.goal_id}  {g.status.value:<9} {g.objective[:60]}"


def _goals(core: JarvisCore, cmd: str, arg: str) -> str:
    """Goal engine front-end (duck-typed through the Core). It only creates, runs, shows and cancels goals; the agents behind it still
    act only through the permission-checked tools, so every confirmation question is asked as usual."""
    sub = core.subsystems.get("goals")
    if sub is None:
        return "Goal Engine: nicht konfiguriert."
    if getattr(sub, "engine", None) is None:
        return f"Goal Engine: deaktiviert – {sub.reason}\nAktivieren: goals.enabled = true und agents.enabled = true (bzw. JARVIS_GOALS_ENABLED=true)"
    engine = sub.engine
    try:
        if cmd == "/goals":
            goals = core.list_goals(limit=15)
            d = engine.describe()
            head = f"Ziele (aktiv {d['active']}/{d['max_active']}):"
            return "\n".join([head] + [("  " + _fmt_goal(g)) for g in goals]) if goals else "Keine Ziele."
        word, _, rest = arg.partition(" ")
        rest = rest.strip()
        if not arg:
            return "Verwendung: /goal <Ziel> [url=… workspace=… runner=… read_paths=a,b] | status <id> | steps <id> | cancel <id>"
        if word == "status" and rest:
            r = engine.result(rest)
            lines = [f"{r.goal.goal_id}: {r.status.value}" + (f" – {r.summary}" if r.summary else ""),
                     f"  Ziel: {r.goal.objective[:200]}", f"  Schritte: {sum(1 for s in r.steps if s.status.value == 'SUCCEEDED')}/{len(r.steps)} erfolgreich"]
            lines += [f"  Hinweis: {w}" for w in r.warnings]
            return "\n".join(lines)
        if word == "steps" and rest:
            steps = engine.steps(rest)
            if not steps:
                return "Noch keine Schritte (nicht geplant)."
            out = []
            for st in steps:
                tries = f" Versuche {st.attempts}/{st.max_attempts}" if st.attempts else ""
                res = f" – {st.result.summary[:80]}" if st.result and st.result.summary else ""
                out.append(f"  {st.step_id:<4} {st.status.value:<9} {st.assigned_agent or 'prüfung':<9}{tries}{res}")
            return "\n".join(out)
        if word == "cancel" and rest:
            rep = core.cancel_goal(rest)
            return f"{rep.goal_id}: {rep.message} ({rep.status.value})"
        context: dict[str, Any] = {}
        for m in _GOAL_OPT.finditer(arg):
            key, val = m.group(1), m.group(2).strip('"')
            context[key] = [p for p in val.split(",") if p] if key == "read_paths" else val
        objective = _GOAL_OPT.sub("", arg).strip()
        goal = core.create_goal(objective, context=context or None)
        print(f"Ziel {goal.goal_id} gestartet … (Strg+C bricht ab)", flush=True)
        try:
            result = core.run_goal(goal.goal_id)
        except KeyboardInterrupt:
            rep = core.cancel_goal(goal.goal_id)
            result = engine.wait(goal.goal_id, timeout=10)
            print(f"Abbruch angefordert: {rep.message}", flush=True)
        lines = [f"Ziel {result.goal.goal_id}: {result.status.value}" + (f" – {result.summary}" if result.summary else "")]
        lines += [f"  {st.step_id}: {st.status.value} {st.assigned_agent or 'prüfung'}" + (f" ({st.attempts} Versuche)" if st.attempts > 1 else "")
                  for st in result.steps]
        lines += [f"  Hinweis: {w}" for w in result.warnings]
        return "\n".join(lines)
    except JarvisError as exc:
        return f"Nicht möglich: {exc}"


_ANALYSIS_HELP = {
    "research": ("Research-Agent", "Goal-Vorlage: template=research_web (+ research={urls:[…]}); liest öffentliche Seiten nur über das Browser-Tool (Berechtigungen gelten).",
                 "/run research action=check_url url=https://…"),
    "business": ("Business-Agent", "Goal-Vorlagen: market_analysis, competitor_analysis, business_analysis, business_plan; Analysen und Entwürfe – sendet nichts.",
                 "/run business action=break_even fixed_costs=2000 price=50 variable_cost=20"),
    "finance": ("Finance-Agent", "Goal-Vorlagen: financial_analysis, company_analysis, paper_trade_analysis; NUR Analyse und Paper-Trading – keine Orders, Überweisungen, Abhebungen.",
                "/run finance action=risk_reward direction=long entry=100 stop=95 target=115"),
}


def _analysis_status(core: JarvisCore, name: str, arg: str) -> str:
    """Status of one analysis capability (duck-typed). Nothing here runs an analysis or bypasses a permission check: work is done by goals/agents and
    the /run calculation tools, both through the permission engine."""
    sub = core.subsystems.get(name)
    title, how, example = _ANALYSIS_HELP[name]
    if sub is None:
        return f"{title}: nicht konfiguriert."
    if arg and arg != "status":
        return f"Verwendung: /{name} [status]\n{how}\nBeispiel: {example}"
    d = sub.describe()
    if d["status"] != "enabled":
        return f"{title}: deaktiviert – {d['reason']}\nAktivieren: {name}.enabled = true (JARVIS_{name.upper()}_ENABLED=true) und agents.enabled = true"
    lines = [f"{title}: aktiv" + ("" if d["registered"] else " – ABER Agent nicht registriert"),
             f"  Agent: {d['agent']} ({d.get('agent_status') or '-'})" + (f" – {d.get('agent_reason')}" if d.get("agent_reason") else ""),
             f"  Aktive/wartende Tasks: {d['active_tasks']}", "  Fähigkeiten: " + ", ".join(d["capabilities"]),
             "  Limits: " + ", ".join(f"{k}={v}" for k, v in d["limits"].items()), "  " + how, "  Beispiel: " + example]
    return "\n".join(lines)


_ARG_PART = re.compile(r"\"([^\"]*)\"|'([^']*)'|([^\"'\s]+)")


def _split_args(arg: str) -> list[str]:
    """Split a command line into words. Quotes group words (a quoted part may sit inside a word: edits="C:\\my dir\\e.json"); backslashes are ALWAYS literal,
    so Windows paths survive (shlex in POSIX mode would eat them). An unbalanced quote raises ValueError."""
    words: list[str] = []
    pos, n = 0, len(arg)
    while pos < n:
        if arg[pos].isspace():
            pos += 1
            continue
        parts: list[str] = []
        while pos < n and not arg[pos].isspace():
            m = _ARG_PART.match(arg, pos)
            if not m:
                raise ValueError("unbalanced quote")
            parts.append(next(g for g in m.groups() if g is not None))
            pos = m.end()
        words.append("".join(parts))
    return words


def _improve(core: JarvisCore, arg: str) -> str:
    """Self-improvement front-end (duck-typed through the Core's subsystems). Approval, activation and rollback are typed by the USER here and confirmed through
    the permission engine's confirmation provider; nothing a model returns can trigger them."""
    import json
    from pathlib import Path
    sub = core.subsystems.get("self_improvement")
    if sub is None:
        return "Selbstverbesserung: nicht konfiguriert."
    mgr = getattr(sub, "manager", None)
    if mgr is None:
        return f"Selbstverbesserung: deaktiviert – {sub.reason}\nAktivieren: self_improvement.enabled = true (JARVIS_SELF_IMPROVEMENT_ENABLED=true)"
    try:
        words = _split_args(arg)
    except ValueError:
        return "Nicht möglich: Anführungszeichen sind nicht ausgeglichen."
    word, rest = (words[0] if words else "list"), words[1:]
    if core.emergency_stopped and word not in ("list", "show"):
        return "Notaus aktiv: /improve ändert nichts, solange der Notaus aktiv ist (nur list und show). Aufheben: /notaus reset"

    def line(p: Any) -> str:
        return f"  {p.proposal_id}  {p.status.value:<18} {p.source:<8} {p.title[:70]}"

    def need_id() -> str:
        if not rest:
            raise JarvisError(f"Verwendung: /improve {word} <id>")
        return rest[0]

    try:
        if word == "list":
            items = mgr.list(limit=20)
            return "\n".join(["Verbesserungsvorschläge:"] + [line(p) for p in items]) if items else "Keine Vorschläge. /improve analyze wertet die vorhandenen Daten aus."
        if word == "analyze":
            rep = mgr.analyze(use_llm="llm" in rest)
            out = [f"Analyse: {len(rep.created)} neue(r) Vorschlag/Vorschläge, {rep.known} bereits bekannt. Quellen: {', '.join(rep.sources_used) or 'keine'}"]
            if rep.sources_missing:
                out.append("  Keine Datengrundlage: " + ", ".join(rep.sources_missing))
            out += [line(p) for p in rep.created] + [f"  Hinweis: {w}" for w in rep.warnings]
            return "\n".join(out)
        if word == "show":
            from jarvis.self_improvement.policy import one_line as q          # text from analysis/logs/models is shown quoted on ONE line, escaped
            p = mgr.get(need_id())
            out = [f"{p.proposal_id}  {p.status.value}  ({p.source}, {p.created_at:%Y-%m-%d %H:%M})", f"  Titel (ungeprueft): {q(p.title)}", f"  Problem (ungeprueft): {q(p.problem, 400)}"]
            out += [f"  Beleg: [{q(e.source, 40)}] {q(e.description, 200)} - {e.count} Datensatz/Datensaetze" for e in p.evidence]
            out += [f"  Aenderung (ungeprueft): {q(p.change, 400)}", f"  Nutzen (ungeprueft): {q(p.benefit, 300)}"] + [f"  Risiko (ungeprueft): {q(r, 200)}" for r in p.risks]
            out += ["  Betrifft (Hinweis): " + q(", ".join(p.affected), 300), "  Tests (Hinweis): " + q(", ".join(p.suggested_tests), 300)]
            out += [f"  {t.at:%H:%M:%S} {(t.old.value if t.old else '-')} -> {t.new.value} ({q(t.actor, 20)})" for t in p.history]
            if p.reason:
                out.append(f"  Grund: {q(p.reason, 300)}")
            return "\n".join(out)
        if word in ("prepare", "test", "submit", "approve", "activate", "rollback") and not mgr.describe()["code_execution"]:
            return ("Nicht moeglich: Vorgeschlagener Code wird in dieser Version nicht vorbereitet, importiert, getestet oder aktiviert - die Ausfuehrungs-Isolation ist nicht "
                    f"nachgewiesen ({mgr.describe()['execution_note']}). Es gibt nur Vorschlaege: /improve analyze | list | show | propose | reject.")
        if word == "propose":
            if len(rest) < 2:
                return 'Verwendung: /improve propose "<Titel>" "<Problem>"'
            return line(mgr.propose(rest[0], rest[1]))
        if word == "prepare":
            pid, opts = need_id(), dict(w.split("=", 1) for w in rest[1:] if "=" in w)
            edits = None
            if "edits" in opts:
                try:
                    edits = json.loads(Path(opts["edits"]).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return "Nicht möglich: edits muss auf eine lesbare JSON-Datei zeigen ([{path, old_text, new_text}, ...])."
            p = mgr.prepare(pid, edits, files=[f for f in opts.get("files", "").split(",") if f])
            return line(p) + (f"\n  {p.reason}" if p.reason else f"\n  Branch {p.branch}: {p.diff_stat}")
        if word == "test":
            print("Tests laufen … (Strg+C bricht ab)", flush=True)
            pid = need_id()
            try:
                p = mgr.test(pid)
            except KeyboardInterrupt:
                mgr.cancel(pid)
                return "Abbruch angefordert."
            return "\n".join([line(p)] + [f"  {s.name}: {'ok' if s.passed else ('FEHLER' if s.executed else 'nicht ausgeführt')}" for s in p.stages] + ([f"  {p.reason}"] if p.reason else []))
        if word == "submit":
            return line(mgr.submit_for_approval(need_id()))
        if word == "approve":
            return line(mgr.approve(need_id())) + "\n  Freigegeben. Aktiviert ist noch nichts (/improve activate <id>)."
        if word == "activate":
            return line(mgr.activate(need_id())) + "\n  Aktiviert. JARVIS neu starten, damit der Code geladen wird."
        if word == "rollback":
            return line(mgr.rollback(need_id()))
        if word == "reject":
            return line(mgr.reject(need_id(), " ".join(rest[1:])))
        if word == "cancel":
            return "Abbruch angefordert." if mgr.cancel(need_id()) else "Es läuft nichts für diesen Vorschlag."
        return "Verwendung: /improve analyze|list|show|propose|prepare|test|submit|approve|activate|rollback|reject|cancel"
    except JarvisError as exc:
        return f"Nicht möglich: {exc}"


_REPAIR_OPT = re.compile(r"(?:^|\s)(workspace|tests|runner|candidates|repair)=(\"[^\"]*\"|'[^']*'|\S+)")


def _repair(core: JarvisCore, arg: str) -> str:
    """Self-test / self-repair front-end (duck-typed through the Core). Runs only in the workspace named in the command; the repair itself is a
    Coding-Agent task, so every write and test run is still confirmed by the permission engine."""
    import json
    sub = core.subsystems.get("self_repair")
    if sub is None:
        return "Self-Repair: nicht konfiguriert."
    if getattr(sub, "engine", None) is None:
        return f"Self-Repair: deaktiviert – {sub.reason}\nAktivieren: self_repair.enabled, agents.enabled und coding.enabled = true (JARVIS_SELF_REPAIR_ENABLED=true)"
    engine = sub.engine
    word, _, rest = arg.partition(" ")
    rest = rest.strip()

    def line(run: Any) -> str:
        return f"  {run.run_id}  {run.status.value:<10} {run.current_phase:<14} Versuche {run.attempt_count}/{run.max_attempts}  {(run.final_summary or run.failure_summary)[:70]}"

    try:
        if not arg or (word == "status" and not rest):
            runs = core.list_repairs(limit=15)
            head = f"Reparaturläufe (aktiv {engine.describe()['active']}/{engine.describe()['max_active']}):"
            return "\n".join([head] + [line(r) for r in runs]) if runs else "Keine Reparaturläufe.\nVerwendung: /repair <Ziel> workspace=\"…\" [tests=… runner=… candidates='[…]'] | status [id] | attempts <id> | cancel <id>"
        if word == "status":
            res = engine.result(rest)
            lines = [line(res.run).strip(), f"  Ziel: {res.run.objective[:200]}"]
            if res.run.failure_summary:
                lines.append(f"  Fehler: {res.run.failure_summary}")
            if res.changed_files:
                lines.append("  Geänderte Dateien: " + ", ".join(res.changed_files))
            lines += [f"  Hinweis: {w}" for w in res.warnings]
            return "\n".join(lines)
        if word == "attempts":
            atts = engine.attempts(rest)
            if not atts:
                return "Noch keine Reparaturversuche."
            out = []
            for a in atts:
                d = a.diagnosis.category.value if a.diagnosis else "-"
                t = "-" if a.targeted_test_result is None else ("PASS" if a.targeted_test_result.passed else "FAIL")
                g = "-" if a.regression_result is None else ("PASS" if a.regression_result.passed else "FAIL")
                out.append(f"  #{a.number} {a.status.value:<9} Diagnose {d:<17} gezielt {t:<4} Regression {g:<4} Dateien: {', '.join(a.changed_files) or '-'}"
                           + (f"  ({a.failure_reason[:60]})" if a.failure_reason else ""))
            return "\n".join(out)
        if word == "cancel" and rest:
            rep = core.cancel_repair(rest)
            return f"{rep.run_id}: {rep.message} ({rep.status.value})"
        context: dict[str, Any] = {}
        workspace = ""
        for m in _REPAIR_OPT.finditer(arg):
            key, val = m.group(1), m.group(2).strip("\"'")
            if key == "workspace":
                workspace = val
            elif key == "tests":
                context["tests"] = [p for p in val.split(",") if p]
            elif key == "candidates":
                context["candidates"] = json.loads(val)
            elif key == "repair":
                context["repair"] = val.lower() in ("1", "true", "ja", "yes")
            else:
                context[key] = val
        objective = _REPAIR_OPT.sub("", arg).strip()
        if not workspace:
            return "Ein Workspace ist erforderlich: /repair <Ziel> workspace=\"<Verzeichnis>\" (nur dort wird getestet/repariert)."
        run = core.create_repair(objective, workspace=workspace, context=context or None)
        print(f"Lauf {run.run_id} gestartet … (Strg+C bricht ab)", flush=True)
        try:
            result = core.run_repair(run.run_id)
        except KeyboardInterrupt:
            rep = core.cancel_repair(run.run_id)
            result = engine.wait(run.run_id, timeout=10)
            print(f"Abbruch angefordert: {rep.message}", flush=True)
        lines = [f"Lauf {result.run.run_id}: {result.status.value}" + (f" – {result.run.final_summary}" if result.run.final_summary else "")]
        lines += [f"  Versuch {a.number}: {a.status.value}" + (f" ({a.failure_reason[:60]})" if a.failure_reason else "") for a in result.attempts]
        lines += [f"  Hinweis: {w}" for w in result.warnings]
        return "\n".join(lines)
    except json.JSONDecodeError:
        return "Nicht möglich: candidates muss gültiges JSON sein."
    except JarvisError as exc:
        return f"Nicht möglich: {exc}"


def _emergency(core: JarvisCore, arg: str) -> str:
    """`/notaus` engages the central emergency stop; `/notaus status` shows it; `/notaus reset` asks (through the permission engine's confirmation) to lift it."""
    engine = core.permissions
    em = getattr(engine, "emergency", None)
    if em is None:
        return "Notaus nicht verfügbar."
    arg = arg.strip().lower()
    if arg in ("", "stop", "an"):
        return em.trigger("Notaus per CLI", "cli").summary()
    if arg == "status":
        return em.report().summary() if em.engaged else "Notaus nicht aktiv."
    if arg == "reset":
        if not em.engaged:
            return "Notaus nicht aktiv."
        res = engine.reset_emergency_stop("cli")
        return res.detail + ("" if not res.problems else "\n  " + "\n  ".join(res.problems))
    return "Verwendung: /notaus | /notaus status | /notaus reset"


def _describe_permissions(core: JarvisCore) -> str:
    d = core.permissions.describe()
    lines = ([f"NOTAUS AKTIV ({d['emergency_stop']['reason']}): alle Anfragen werden verweigert. Aufheben: /notaus reset"]
             if d.get("emergency_stop", {}).get("engaged") else [])
    lines += [f"Modus: {d['mode']}   Bestätigung: {d['confirmation'] or 'keine (Rückfrage nicht möglich)'}",
             "Erlaubte Verzeichnisse: " + (", ".join(d["roots"]) or "keine"),
             "Gesperrte Pfade: " + (", ".join(d["denied_paths"]) or "keine")]
    lines.append("Regeln: " + ("" if d["rules"] else "keine"))
    lines += [f"  {r['id']}: {r['effect']} tool={r['tool'] or '*'} action={r['action'] or '*'}" for r in d["rules"]]
    grants = d["session_grants"]
    lines.append("Sitzungsfreigaben: " + ("" if grants else "keine"))
    lines += [f"  {g['tool']}.{g['action']} {g['resource']}" for g in grants]
    return "\n".join(lines)


def _tail_audit(core: JarvisCore, arg: str) -> str:
    n = int(arg) if arg.isdigit() else 10
    events = core.permissions.audit.tail(n)
    if not events:
        return "Keine Sicherheitsereignisse protokolliert."
    def line(e: dict) -> str:
        what = f"{e['tool']}.{e['action']}" if e.get("tool") and e.get("action") else e.get("tool", "")
        parts = [e.get("timestamp", "")[11:19], e.get("type", "?"), what, e.get("status", ""), e.get("detail", "")]
        return "  " + " ".join(p for p in parts if p)

    return "\n".join(line(e) for e in events)


def _voice(core: JarvisCore, settings: Settings | None, display: Callable[[str], None] = print,
           input_fn: Callable[[str], str] = input) -> str:
    """Run the voice loop; any voice problem degrades to a message and the text CLI keeps working."""
    if core.emergency_stopped:
        return "Notaus aktiv: der Sprachmodus startet nicht (das Mikrofon bleibt aus). Aufheben: /notaus reset"
    if settings is None:
        return "Sprachmodus nicht konfiguriert."
    try:
        session = build_voice_session(settings, core, display, input_fn)
    except VoiceError as exc:
        return f"Sprachmodus nicht verfügbar: {exc}\nText-CLI bleibt aktiv."
    except JarvisError as exc:
        return f"Sprachmodus konnte nicht gestartet werden: {exc}"
    display("Sprachmodus aktiv (Wake-Word: "
            f"{settings.voice.wake_word if settings.voice.require_wake_word else 'nicht nötig'}; „exit“ beendet).")
    try:
        session.run()
    except KeyboardInterrupt:
        pass
    return "Zurück im Text-Modus."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS personal AI assistant")
    parser.add_argument("-c", "--config", help="path to a TOML config file")
    parser.add_argument("--voice", action="store_true", help="start in voice mode")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config or _default_config())
        core = build_core(settings)
    except JarvisError as exc:
        print(f"Startfehler: {exc}", file=sys.stderr)
        return 2
    repl(core, settings=settings, start_voice=args.voice)
    return 0


def _default_config() -> str | None:
    from pathlib import Path
    for candidate in (Path("jarvis.local.toml"), Path("config/jarvis.toml")):
        if candidate.is_file():
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
