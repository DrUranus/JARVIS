"""Command-line test interface (`jarvis`)."""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Callable, Sequence

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
  /computer      Status der Computersteuerung (stop = Notaus, resume = fortsetzen)
  /browser       Browser-Agent: Status | start | stop | pages | halt (Notaus) | resume (sonst: /run browser action=...)
  /coding        Coding-Agent: Status | halt (Notaus) | resume | stop (Sitzung beenden) (sonst: /run coding action=...)
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
    if cmd == "/permissions":
        return _describe_permissions(core)
    if cmd == "/audit":
        return _tail_audit(core, arg)
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


def _describe_permissions(core: JarvisCore) -> str:
    d = core.permissions.describe()
    lines = [f"Modus: {d['mode']}   Bestätigung: {d['confirmation'] or 'keine (Rückfrage nicht möglich)'}",
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
