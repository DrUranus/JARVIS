"""Command-line test interface (`jarvis`)."""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

from jarvis import __version__
from jarvis.bootstrap import build_core, build_voice_session
from jarvis.config import load_settings
from jarvis.config import Settings
from jarvis.core import JarvisCore
from jarvis.errors import JarvisError, VoiceError

HELP = """Befehle:
  /plan <ziel>   Plan für ein Ziel erstellen
  /tasks         Offene Tasks anzeigen
  /tools         Registrierte Tools anzeigen
  /reset         Gesprächskontext löschen
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
    if cmd == "/voice":
        return _voice(core, settings, output_fn, input_fn)
    if cmd == "/plan":
        return core.plan(arg).text if arg else "Verwendung: /plan <ziel>"
    return f"Unbekannter Befehl: {cmd}. /help zeigt alle Befehle."


def repl(core: JarvisCore, input_fn: Callable[[str], str] | None = None,
         output_fn: Callable[[str], None] | None = None, settings: Settings | None = None,
         start_voice: bool = False) -> None:
    input_fn, output_fn = input_fn or input, output_fn or print
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
