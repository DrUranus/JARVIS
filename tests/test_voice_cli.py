"""CLI integration: voice is an extra interface; text CLI keeps working."""
from dataclasses import replace

from jarvis.config import Settings, VoiceSettings
from jarvis.errors import VoiceUnavailableError
from jarvis.voice.devices import SoundDeviceSource
from jarvis.interface.cli import main, repl, run_command


def run(core, lines, settings=None, **kw):
    it = iter(lines)
    out = []

    def fake_input(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    repl(core, fake_input, out.append, settings=settings, **kw)
    return "\n".join(out)


def test_voice_command_runs_console_voice_then_returns_to_text(core):
    out = run(core, ["/voice", "Hallo", "exit", "/tools", "/exit"], Settings())
    assert "Sprachmodus aktiv" in out and "JARVIS: ok" in out
    assert "🔊" in out and "Zurück im Text-Modus." in out
    assert "echo:" in out and out.endswith("Bis bald.")  # text CLI still works afterwards


def test_voice_flag_starts_in_voice_mode(core):
    out = run(core, ["Hallo", "exit", "/exit"], Settings(), start_voice=True)
    assert out.index("Sprachmodus aktiv") < out.index("Zurück im Text-Modus.")


def test_voice_unavailable_falls_back_to_text(core, monkeypatch):
    def no_mic():
        raise VoiceUnavailableError("no microphone backend")

    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(no_mic))  # independent of an installed sounddevice
    s = replace(Settings(), voice=VoiceSettings(stt_provider="mock"))  # needs microphone lib -> absent here
    out = run(core, ["/voice", "Hallo", "/exit"], s)
    assert "Sprachmodus nicht verfügbar" in out and "Text-CLI bleibt aktiv" in out
    assert "\nok\n" in out  # text dialog unaffected (fixture core answers "ok")


def test_voice_without_settings_is_harmless(core):
    assert run_command(core, "/voice") == "Sprachmodus nicht konfiguriert."


def test_main_accepts_voice_flag(monkeypatch, capsys):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert main(["--voice"]) == 0
    assert "Sprachmodus aktiv" in capsys.readouterr().out


def test_run_arguments_keep_windows_backslashes():
    from jarvis.interface.cli import _split_tool_args
    line = r'filesystem path="C:\Users\me\a b.txt" x=C:\tmp\f.txt'
    assert _split_tool_args(line, windows=True) == ["filesystem", r"path=C:\Users\me\a b.txt", r"x=C:\tmp\f.txt"]
    assert _split_tool_args(r"t a='x y'", windows=False) == ["t", "a=x y"]
