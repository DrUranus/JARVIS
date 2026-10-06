"""Command-line test interface (`jarvis`)."""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

from jarvis import __version__
from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.core import JarvisCore
from jarvis.errors import JarvisError

HELP = """Befehle:
  /plan <ziel>   Plan für ein Ziel erstellen
  /tasks         Offene Tasks anzeigen
  /tools         Registrierte Tools anzeigen
  /reset         Gesprächskontext löschen
  /help          Diese Hilfe
  /exit          Beenden"""

PROMPT = "jarvis> "


def run_command(core: JarvisCore, line: str) -> str | None:
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
    if cmd == "/plan":
        return core.plan(arg).text if arg else "Verwendung: /plan <ziel>"
    return f"Unbekannter Befehl: {cmd}. /help zeigt alle Befehle."


def repl(core: JarvisCore, input_fn: Callable[[str], str] = input,
         output_fn: Callable[[str], None] = print) -> None:
    output_fn(f"JARVIS {__version__} – /help für Befehle, /exit zum Beenden.")
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
                out = run_command(core, line)
                if out is None:
                    output_fn("Bis bald.")
                    return
            else:
                out = core.handle(line).text
        except JarvisError as exc:
            out = f"Fehler: {exc}"
        output_fn(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS personal AI assistant")
    parser.add_argument("-c", "--config", help="path to a TOML config file")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config or _default_config())
        core = build_core(settings)
    except JarvisError as exc:
        print(f"Startfehler: {exc}", file=sys.stderr)
        return 2
    repl(core)
    return 0


def _default_config() -> str | None:
    from pathlib import Path
    for candidate in (Path("jarvis.local.toml"), Path("config/jarvis.toml")):
        if candidate.is_file():
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
