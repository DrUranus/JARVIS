"""WP06: Not-Aus waehrend eines haengenden UIA-Aufrufs, Race-Schleife um `halt()`, wiederholte Haenger und die repositoryweite Importgrenze der UIA-Bibliotheken.

Reine Fakes (kleine Worker-Prozesse ohne pywinauto), Linux und Windows gleich, kein Netzwerk. Die Tests aendern keine Sicherheitsregel: sie belegen nur, dass `halt()` jeden
laufenden Aufruf beendet, dass nie ein unerwarteter Ausnahmetyp entsteht und dass ein Haenger den Provider nicht dauerhaft blockiert."""
from __future__ import annotations

import ast
import random
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from jarvis.computer import ComputerError, ErrorCode
from jarvis.computer.providers.pywinauto_uia import PywinautoUiaProvider
from jarvis.computer.providers.pywinauto_uia_actions import PywinautoUiaActionProvider
from jarvis.computer.uia import UiLimits
from jarvis.computer.uia_actions import UiAction, UiTarget
from test_computer_uia_provider import WORKER_SCRIPT

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
HANG = 98                                                                  # das Test-Fenster 98 schlaeft 60 s im Worker (siehe WORKER_SCRIPT)
TARGET = UiTarget("0.1", "Newsletter", "CheckBox", "news")

ACT_STUB = textwrap.dedent('''
    import sys, time
    from jarvis.computer.providers import uia_act_worker as w

    class A:
        def state(self, *a):
            time.sleep(60)
        def act(self, *a):
            time.sleep(60)

    w.serve(A(), sys.stdin, sys.stdout)
''')


@pytest.fixture()
def worker_cmd(tmp_path):
    path = tmp_path / "fake_worker.py"
    path.write_text(WORKER_SCRIPT, encoding="utf-8")
    return [sys.executable, "-u", str(path)]


@pytest.fixture()
def provider(worker_cmd):
    made = []

    def build(**kw):
        kw.setdefault("worker_command", worker_cmd)
        kw.setdefault("call_timeout", 15.0)
        p = PywinautoUiaProvider(**kw)
        made.append(p)
        return p

    yield build
    for p in made:
        p.shutdown()


def in_thread(fn, *args):
    """Run `fn` in a thread and collect result or exception; never raises into the test thread."""
    box: dict = {}

    def run():
        try:
            box["result"] = fn(*args)
        except BaseException as exc:                                           # noqa: BLE001 - the type of the exception is exactly what the tests inspect
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


# ---- Importgrenze (P3), repositoryweit --------------------------------------------------------------------------------------------------------
ALLOWED = {"pywinauto": {"computer/providers/uia_worker.py", "computer/providers/uia_act_worker.py"},
           "comtypes": {"computer/providers/uia_worker.py", "computer/providers/uia_act_worker.py"},
           "pythoncom": {"computer/providers/uia_worker.py", "computer/providers/uia_act_worker.py"},
           "win32api": set(), "win32gui": set(), "win32com": set(),
           "mss": {"computer/providers/mss_screen.py"}, "pyautogui": {"computer/providers/pyautogui_input.py"}}


def imported_roots(source: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):                                   # ast.walk: auch verschachtelte (lazy) Importe zaehlen
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


def violations(files: dict[str, str]) -> list[tuple[str, str]]:
    return sorted((rel, lib) for rel, text in files.items() for lib in imported_roots(text) & ALLOWED.keys() if rel not in ALLOWED[lib])


def test_automation_libraries_are_imported_only_by_their_own_worker_or_provider_modules():
    files = {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")}
    assert len(files) > 100
    assert violations(files) == []
    for lib, owners in ALLOWED.items():                                        # die Erlaubnisliste ist kein toter Text: jeder Eigentuemer importiert seine Bibliothek wirklich
        for rel in owners:
            assert lib in imported_roots(files[rel]) or lib in {"comtypes", "pythoncom"}, (lib, rel)


def test_the_structure_test_detects_a_forbidden_import_even_if_it_is_lazy_or_nested():
    bad = {"computer/other.py": "def f():\n    import pywinauto\n", "gui/x.py": "from comtypes.client import CreateObject\n", "computer/providers/uia_worker.py": "import pywinauto\n"}
    assert violations(bad) == [("computer/other.py", "pywinauto"), ("gui/x.py", "comtypes")]


# ---- Not-Aus waehrend eines haengenden Aufrufs (P1) ---------------------------------------------------------------------------------------------
def test_halt_ends_a_hanging_call_quickly_and_the_provider_recovers_after_resume(provider):
    p = provider(call_timeout=30.0)
    t, box = in_thread(p.describe, HANG, UiLimits())
    time.sleep(0.4)
    start = time.monotonic()
    p.halt("Notaus")
    t.join(5)
    assert not t.is_alive(), "the hanging call must end after halt()"
    assert time.monotonic() - start < 3
    assert isinstance(box.get("error"), ComputerError) and box["error"].code is ErrorCode.FAILSAFE, box
    assert not p.worker_running
    for call in (lambda: p.describe(11, UiLimits()), p.list_windows):
        with pytest.raises(ComputerError) as e:
            call()
        assert e.value.code is ErrorCode.FAILSAFE
    p.resume()
    assert p.describe(11, UiLimits()).node_count == 4


def test_two_hangs_in_a_row_each_restart_the_worker_and_never_reset_the_session_budget(provider):
    p = provider(call_timeout=1.0, max_calls=5)
    for _ in range(2):
        with pytest.raises(ComputerError) as e:
            p.describe(HANG, UiLimits())
        assert e.value.code is ErrorCode.BACKEND_ERROR and "timeout" in e.value.message.lower() and not p.worker_running
    assert p.describe(11, UiLimits()).node_count == 4 and p.workers_started == 3
    p.halt("x")
    p.resume()
    assert p.calls_used == 3                                                   # halt/resume setzen das Sitzungsbudget nie zurueck


def test_halt_at_random_moments_never_produces_an_unexpected_exception_or_a_stuck_thread(provider):
    rnd = random.Random(20261112)
    p = provider(call_timeout=10.0)
    unexpected = []
    for i in range(30):
        p.resume()
        t, box = in_thread(p.describe, 11, UiLimits())
        time.sleep(rnd.uniform(0.0, 0.30))
        p.halt(f"race-{i}")
        t.join(8)
        assert not t.is_alive(), f"iteration {i}: call stuck after halt"
        err = box.get("error")
        if err is not None and not isinstance(err, ComputerError):
            unexpected.append((i, type(err).__name__, str(err)[:80]))
        if isinstance(err, ComputerError):
            assert err.code is ErrorCode.FAILSAFE, (i, err.code)                 # nach halt() ist jeder Abbruch ein definierter FAILSAFE
        assert not p.worker_running
    assert unexpected == []


def test_a_halted_provider_refuses_calls_that_start_after_the_halt(provider):
    p = provider()
    p.halt("Notaus")
    for _ in range(5):
        with pytest.raises(ComputerError) as e:
            p.describe(11, UiLimits())
        assert e.value.code is ErrorCode.FAILSAFE
    assert p.workers_started == 0


# ---- Aktions-Provider (gleiche Prozessfuehrung ueber `_link`) --------------------------------------------------------------------------------------
@pytest.fixture()
def act_provider(tmp_path):
    script = tmp_path / "act_stub.py"
    script.write_text(ACT_STUB, encoding="utf-8")
    p = PywinautoUiaActionProvider(max_calls=10, call_timeout=30.0, worker_command=[sys.executable, "-u", str(script)])
    yield p
    p.shutdown()


@pytest.mark.parametrize("op", ["state", "act"])
def test_halt_ends_a_hanging_action_provider_call(act_provider, op):
    call = (lambda: act_provider.read_state(5, TARGET)) if op == "state" else (lambda: act_provider.perform(5, TARGET, UiAction.TOGGLE))
    t, box = in_thread(call)
    time.sleep(0.4)
    act_provider.halt("Notaus")
    t.join(5)
    assert not t.is_alive()
    assert isinstance(box.get("error"), ComputerError) and box["error"].code is ErrorCode.FAILSAFE, box
    assert not act_provider.worker_running
    with pytest.raises(ComputerError) as e:
        act_provider.read_state(5, TARGET)
    assert e.value.code is ErrorCode.FAILSAFE


def test_the_action_provider_halt_race_loop_has_no_unexpected_exception(tmp_path):
    script = tmp_path / "act_fast.py"
    script.write_text(ACT_STUB.replace("time.sleep(60)", "return {'enabled': True, 'visible': True, 'is_password': False, 'patterns': ['toggle'], 'value': None, "
                                                               "'read_only': None, 'toggle_state': 'off', 'selected': None, 'has_focus': False}"), encoding="utf-8")
    p = PywinautoUiaActionProvider(max_calls=200, call_timeout=10.0, worker_command=[sys.executable, "-u", str(script)])
    rnd = random.Random(7)
    try:
        for i in range(25):
            p.resume()
            t, box = in_thread(p.read_state, 5, TARGET)
            time.sleep(rnd.uniform(0.0, 0.30))
            p.halt("race")
            t.join(8)
            assert not t.is_alive()
            err = box.get("error")
            assert err is None or (isinstance(err, ComputerError) and err.code is ErrorCode.FAILSAFE), (i, type(err).__name__, str(err)[:80])
    finally:
        p.shutdown()


# ---- N2-Reparatur: halt() zwischen Pruefung, Worker-Start und Anfrage (deterministisch) -------------------------------------------------------------
def test_halt_between_worker_start_and_request_is_a_clean_failsafe_error(provider):
    """Vorher: AssertionError (`assert self._proc is not None`), weil halt() den Worker nach dem Start, aber vor dem Schreiben der Anfrage entfernte."""
    p = provider(call_timeout=5.0)
    start = p._start_worker

    def hooked():
        start()
        p.halt("zwischen Start und Anfrage")                                   # genau das Fenster nach dem Worker-Start und vor dem Schreiben der Anfrage

    p._start_worker = hooked
    with pytest.raises(ComputerError) as e:
        p.describe(11, UiLimits())
    assert e.value.code is ErrorCode.FAILSAFE and not p.worker_running
    p.resume()
    p._start_worker = start
    assert p.describe(11, UiLimits()).node_count == 4                          # nach resume() wieder nutzbar


def test_halt_after_the_halted_check_but_before_the_worker_starts_never_leaves_a_running_worker(provider):
    """Vorher: der Aufruf startete nach halt() einen NEUEN Worker und fuehrte die Anfrage aus (Lesezugriff nach dem Not-Aus)."""
    p = provider(call_timeout=5.0)
    start = p._start_worker

    def hooked():
        p.halt("vor dem Worker-Start")                                          # halt() nach der `_halted`-Pruefung, bevor der Worker gestartet wird
        start()

    p._start_worker = hooked
    with pytest.raises(ComputerError) as e:
        p.describe(11, UiLimits())
    assert e.value.code is ErrorCode.FAILSAFE
    assert not p.worker_running                                                # der Worker bleibt gestoppt
    p._start_worker = start
    with pytest.raises(ComputerError) as e2:
        p.describe(11, UiLimits())
    assert e2.value.code is ErrorCode.FAILSAFE and not p.worker_running


def test_halt_after_the_request_was_written_ends_the_call_with_failsafe_not_a_backend_error(provider):
    p = provider(call_timeout=30.0)
    t, box = in_thread(p.describe, HANG, UiLimits())
    time.sleep(0.4)
    p.halt("Notaus")
    t.join(5)
    assert not t.is_alive() and isinstance(box.get("error"), ComputerError) and box["error"].code is ErrorCode.FAILSAFE
