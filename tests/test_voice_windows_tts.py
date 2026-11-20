"""WP05b: Windows-Sprachausgabe mit Windows-Bordmitteln (PowerShell 5.1 + System.Speech) als TTS-Provider `windows`.

Nur Fakes: kein echter Prozess, keine Audiogeraete, kein Netz (Linux und Windows gleich). Geprueft wird: feste Argumentliste (Text NIE im Argument), Text nur ueber stdin (UTF-8),
Injektionstexte, Bereinigung/Begrenzung/Aufteilung (D3), Zeitlimit, Fehlerabbildung ohne Textinhalt, Abbruch (`stop()`), Not-Aus (N1/D4: nichts Neues bei aktivem Not-Aus, keine alte
Warteschlange, Stopper `voice`), Strukturtest (kein shell=True, keine Textinterpolation) und die Standardeinstellung (`console`)."""
from __future__ import annotations

import ast
import subprocess
import threading
import time
from pathlib import Path

import pytest

from jarvis.config import VoiceSettings
from jarvis.errors import TTSError, VoiceUnavailableError
from jarvis.voice import build_speaker
from jarvis.voice.console import ConsoleSpeaker
from jarvis.voice.factory import TTS_PROVIDERS
from jarvis.voice.windows_tts import SCRIPT, WindowsTTS

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
MODULE = SRC / "voice" / "windows_tts.py"
INJECTIONS = ['"; Stop-Process -Name explorer; "', "$(Remove-Item -Recurse C:\\)", "`n`r Invoke-Expression 'calc'", "' ; calc ; '", "-Command whoami", "| format-hex",
              "%PATH% & del *.*", "{ iex $t }", "<#", "\x00\x1b[2J", "-ExecutionPolicy Bypass", "-Command -"]


class FakeProc:
    """Verhaelt sich wie subprocess.Popen: communicate() blockiert, bis `finish`/kill, dann Rueckgabecode."""

    def __init__(self, args, kwargs, rc=0, hang=False, err=b""):
        self.args, self.kwargs, self.rc, self.hang, self.err = args, kwargs, rc, hang, err
        self.stdin_data = None
        self.pid = 4242
        self.killed = threading.Event()
        self.returncode = None
        self.timeout_seen = None

    def communicate(self, input=None, timeout=None):                       # noqa: A002 - wie subprocess.Popen
        self.stdin_data, self.timeout_seen = input, timeout
        if self.hang:
            if not self.killed.wait(timeout if timeout is not None else 30):
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = -9
        else:
            self.returncode = self.rc
        return b"", self.err

    def kill(self):
        self.killed.set()

    def poll(self):
        return self.returncode


class Factory:
    def __init__(self, **proc_kw):
        self.proc_kw, self.procs, self.error = proc_kw, [], None

    def __call__(self, args, **kwargs):
        if self.error:
            raise self.error
        p = FakeProc(args, kwargs, **self.proc_kw)
        self.procs.append(p)
        return p


def make(**kw):
    popen = Factory(**{k: kw.pop(k) for k in ("rc", "hang", "err") if k in kw})
    return WindowsTTS(popen=popen, contain=lambda pid: None, **kw), popen


# ---- Befehlszeile und stdin ------------------------------------------------------------------------------------------------------------------------
def test_the_command_line_is_fixed_and_the_text_goes_only_through_stdin():
    tts, popen = make()
    tts.speak("Hallo Welt. Größe, Übung, Straße!")
    (p,) = popen.procs
    assert p.args == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT]
    assert p.kwargs["shell"] is False and p.kwargs["stdin"] == subprocess.PIPE
    assert p.stdin_data.decode("utf-8") == "Hallo Welt. Größe, Übung, Straße!"
    assert "Hallo" not in " ".join(p.args) and "Größe" not in repr(p.kwargs.get("env", ""))
    assert "-ExecutionPolicy" not in p.args and "-Command" in p.args and p.args[p.args.index("-Command") + 1] != "-"


def test_the_script_reads_stdin_as_data_with_explicit_utf8_and_never_executes_it():
    assert "OpenStandardInput" in SCRIPT and "GetString" in SCRIPT and "UTF8" in SCRIPT                   # Bytes explizit als UTF-8 lesen, unabhaengig von der Konsolenkodierung
    assert "Invoke-Expression" not in SCRIPT and "iex" not in SCRIPT.lower().split() and '"' not in SCRIPT and "ExecutionPolicy" not in SCRIPT
    assert "System.Speech" in SCRIPT and "GetInstalledVoices" in SCRIPT


@pytest.mark.parametrize("text", INJECTIONS)
def test_injection_texts_never_change_the_command_line(text):
    tts, popen = make()
    tts.speak("Bitte sprich: " + text)
    (p,) = popen.procs
    assert p.args == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT]
    assert b"\x00" not in p.stdin_data and b"\x1b" not in p.stdin_data


# ---- Bereinigung, Begrenzung, Aufteilung (D3) ---------------------------------------------------------------------------------------------------
def test_control_characters_are_removed_and_whitespace_is_collapsed():
    tts, popen = make()
    tts.speak("a\x00b\x07c\x1b[0m   d\t\te\r\nf")
    assert popen.procs[0].stdin_data.decode() == "abc[0m d e f"


@pytest.mark.parametrize("text", ["", "   ", "\x00\x01\x02", "\n\n"])
def test_empty_text_starts_nothing(text):
    tts, popen = make()
    tts.speak(text)
    assert popen.procs == []


def test_long_text_is_split_into_bounded_sections_at_sentence_boundaries():
    tts, popen = make(chunk_chars=80, max_chars=1000)
    sentence = "Dies ist ein vollständiger Satz mit etwas Länge. "
    tts.speak(sentence * 12)
    (p,) = popen.procs
    parts = p.stdin_data.decode().split("\n")
    assert 2 <= len(parts) <= 12 and all(0 < len(x) <= 80 for x in parts) and all(x.endswith(".") for x in parts)
    assert " ".join(parts).replace("  ", " ").strip() == (sentence * 12).strip()[:len(" ".join(parts))]


def test_a_single_overlong_sentence_is_split_at_word_boundaries_not_in_the_middle_of_words():
    tts, popen = make(chunk_chars=40, max_chars=1000)
    tts.speak(" ".join(["Wort%02d" % i for i in range(30)]))
    parts = popen.procs[0].stdin_data.decode().split("\n")
    assert all(len(x) <= 40 for x in parts) and all(w.startswith("Wort") and len(w) == 6 for x in parts for w in x.split())


def test_the_total_length_is_bounded_so_no_endless_queue_can_build_up():
    tts, popen = make(chunk_chars=100, max_chars=500)
    tts.speak("Satz eins ist hier. " * 5000)
    data = popen.procs[0].stdin_data.decode()
    assert len(data.replace("\n", " ")) <= 500 and len(data.split("\n")) <= 5 + 1
    assert len(popen.procs) == 1                                                                         # ein Prozess, keine Warteschlange von Prozessen


def test_the_timeout_scales_with_the_text_but_is_bounded():
    tts, popen = make()
    tts.speak("Kurz.")
    tts.speak("x " * 1000)
    short, long_ = (p.timeout_seen for p in popen.procs)
    assert 0 < short < long_ <= 300


# ---- Fehlerabbildung ------------------------------------------------------------------------------------------------------------------------------
def test_a_missing_powershell_is_reported_as_unavailable_without_the_text():
    tts, popen = make()
    popen.error = FileNotFoundError("powershell.exe")
    with pytest.raises(VoiceUnavailableError) as e:
        tts.speak("geheimer Text sk-ABCDEF")
    assert "PowerShell" in str(e.value) and "geheimer" not in str(e.value) and "sk-" not in str(e.value)


def test_no_installed_voice_is_reported_as_unavailable():
    tts, _ = make(rc=3)
    with pytest.raises(VoiceUnavailableError) as e:
        tts.speak("Hallo.")
    assert "Stimme" in str(e.value)


def test_other_failures_are_tts_errors_without_stderr_or_text():
    tts, _ = make(rc=1, err=b"Cannot speak 'geheimer Text sk-ABCDEF'")
    with pytest.raises(TTSError) as e:
        tts.speak("geheimer Text sk-ABCDEF")
    assert "geheimer" not in str(e.value) and "sk-" not in str(e.value) and "1" in str(e.value)


def test_an_os_error_while_starting_is_a_tts_error():
    tts, popen = make()
    popen.error = PermissionError("denied")
    with pytest.raises(TTSError):
        tts.speak("Hallo.")


def test_the_timeout_kills_the_process_and_raises_a_tts_error():
    tts, popen = make(hang=True, timeout=0.3)
    with pytest.raises(TTSError) as e:
        tts.speak("Hallo.")
    assert "Zeit" in str(e.value) and popen.procs[0].killed.is_set()
    assert not tts.speaking


# ---- Abbruch (stop) ------------------------------------------------------------------------------------------------------------------------------
def run_in_thread(fn, *a):
    box = {}

    def run():
        try:
            box["result"] = fn(*a)
        except BaseException as exc:                                                                        # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def wait_for(cond, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_stop_ends_a_running_speech_quickly_and_is_not_an_error():
    tts, popen = make(hang=True, timeout=30)
    t, box = run_in_thread(tts.speak, "Ein langer Text.")
    assert wait_for(lambda: tts.speaking)
    tts.stop()
    t.join(3)
    assert not t.is_alive() and "error" not in box and popen.procs[0].killed.is_set() and not tts.speaking


def test_stop_is_idempotent_and_never_raises_even_without_a_running_speech():
    tts, _ = make()
    for _ in range(3):
        tts.stop()


def test_nothing_that_was_cut_off_is_replayed_and_new_speech_works_again():
    tts, popen = make(hang=True, timeout=30)
    t, _ = run_in_thread(tts.speak, "Alter Text, der abgebrochen wird.")
    assert wait_for(lambda: tts.speaking)
    tts.stop()
    t.join(3)
    popen.proc_kw["hang"] = False
    tts.speak("Neuer Text.")
    assert [p.stdin_data.decode() for p in popen.procs] == ["Alter Text, der abgebrochen wird.", "Neuer Text."]          # genau je einmal, keine Wiederholung
    assert len(popen.procs) == 2


# ---- Not-Aus (N1, D4) ------------------------------------------------------------------------------------------------------------------------------
def test_no_speech_starts_while_the_emergency_stop_is_active_and_nothing_is_replayed_after_the_reset():
    state = {"reason": "Notaus aktiv (test)"}
    tts, popen = make()
    tts.guard = lambda: state["reason"]
    tts.speak("Darf nicht gesprochen werden.")
    tts.speak("Auch nicht.")
    assert popen.procs == []
    state["reason"] = None                                                                                   # Aufhebung des Not-Aus
    tts.speak("Jetzt wieder.")
    assert [p.stdin_data.decode() for p in popen.procs] == ["Jetzt wieder."]


def test_a_failing_guard_blocks_the_speech_fail_closed():
    tts, popen = make()
    tts.guard = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    tts.speak("Hallo.")
    assert popen.procs == []


def test_the_voice_stopper_stops_a_running_speech_and_reports_honestly():
    from jarvis.bootstrap import voice_stopper
    from jarvis.permissions.emergency import StopOutcome
    tts, popen = make(hang=True, timeout=30)
    speaker = build_speaker_with(tts)
    stop = voice_stopper(speaker)
    assert stop("test").outcome is StopOutcome.NOTHING
    t, _ = run_in_thread(tts.speak, "Langer Text.")
    assert wait_for(lambda: tts.speaking)
    res = stop("test")
    t.join(3)
    assert res.outcome is StopOutcome.STOPPED and popen.procs[0].killed.is_set()


def build_speaker_with(tts):
    from jarvis.voice.composed import TTSSpeaker
    return TTSSpeaker(tts)


# ---- Registrierung, Standard, Struktur -------------------------------------------------------------------------------------------------------------
def test_the_provider_is_registered_and_the_default_stays_console():
    assert "windows" in TTS_PROVIDERS.names()
    assert VoiceSettings().tts_provider == "console" and isinstance(build_speaker(VoiceSettings()), ConsoleSpeaker)
    assert isinstance(TTS_PROVIDERS.create("windows", VoiceSettings()), WindowsTTS)


def test_the_module_has_no_shell_no_interpolation_of_text_and_no_forbidden_switches():
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert isinstance(node.value, ast.Constant) and node.value.value is False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
            assert node.func.attr not in ("system", "popen", "startfile")
    assert "shell=True" not in src and "os.system" not in src and "ExecutionPolicy" not in src and '"-Command", "-"' not in src
    argv_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_argv")
    assert not any(isinstance(n, (ast.JoinedStr, ast.Mod)) for n in ast.walk(argv_fn)) and "format" not in ast.unparse(argv_fn)          # Argumentaufbau ohne Textinterpolation
    assert "text" not in {a.arg for a in argv_fn.args.args}                                                                               # _argv bekommt den Text nie


def test_the_system_tts_module_is_unchanged_and_has_no_windows_code():
    src = (SRC / "voice" / "system_tts.py").read_text(encoding="utf-8")
    assert "powershell" not in src.lower() and "System.Speech" not in src


# ---- Verdrahtung in bootstrap.py (N1): Stopper "voice" und Guard ---------------------------------------------------------------------------------
def test_build_voice_session_registers_the_voice_stopper_and_wires_the_emergency_guard():
    from jarvis.bootstrap import build_core, build_voice_session
    from jarvis.config import load_settings
    settings = load_settings(env={"JARVIS_VOICE_STT_PROVIDER": "mock", "JARVIS_VOICE_AUDIO_INPUT": "mock", "JARVIS_VOICE_TTS_PROVIDER": "windows"})
    core = build_core(settings)
    session = build_voice_session(settings, core)
    assert "voice" in core.permissions.emergency.names()
    tts = session._speaker._tts
    assert isinstance(tts, WindowsTTS) and tts.guard is not None and tts.guard() is None
    core.permissions.emergency.engage("test")
    assert tts.guard() and "Notaus" in tts.guard()                                                      # aktiver Not-Aus -> keine neue Sprachausgabe
    tts._popen = Factory()
    tts.speak("Darf nicht gesprochen werden.")
    assert tts._popen.procs == []
    report = core.permissions.emergency.run_stoppers()
    assert any(c.name == "voice" for c in report.components)


def test_the_console_default_still_builds_a_session_and_interrupt_is_harmless():
    from jarvis.bootstrap import build_core, build_voice_session
    from jarvis.config import load_settings
    settings = load_settings(env={"JARVIS_VOICE_STT_PROVIDER": "console", "JARVIS_VOICE_TTS_PROVIDER": "console"})
    core = build_core(settings)
    session = build_voice_session(settings, core)
    session.interrupt()                                                                                   # ConsoleSpeaker: nichts zu stoppen, wirft nicht
