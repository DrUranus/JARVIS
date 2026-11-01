"""Lesender UIA-Provider (Backlog-Schritt uia-provider-readonly).

Linux und Windows: Protokoll, Zeitlimit, Notaus, Sitzungsbudget, Passwortfelder, fehlende Bibliothek, Strukturtests (keine Eingabe, kein Klick) -
mit einem kleinen Test-Worker, der denselben Protokollkern (`serve`) wie der echte Worker benutzt, aber keine Bibliothek braucht.
Nur Windows: `TestRealWindow` liest ein echtes, per Subprozess gestartetes Notepad-Fenster mit pywinauto. Dort gibt es kein Ueberspringen
bei fehlender Bibliothek: fehlt sie, schlaegt der Test fehl. Kein Netzwerk."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap
import time
import tomllib
from pathlib import Path

import pytest

from jarvis.computer import ComputerError, ErrorCode
from jarvis.computer.errors import ComputerUnavailableError
from jarvis.computer.uia import HARD_MAX_NODES, ControlType, UiLimits, UiQuery, UiTreeProvider

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "src" / "jarvis" / "computer"
PROVIDER_FILE = COMP / "providers" / "pywinauto_uia.py"
WORKER_FILE = COMP / "providers" / "uia_worker.py"
SECRET = "hunter2-geheim"

WORKER_SCRIPT = textwrap.dedent('''
    import sys, time
    from jarvis.computer.providers.uia_worker import serve

    def node(rid, name, ctype, children=(), **kw):
        d = {"runtime_id": rid, "name": name, "control_type": ctype, "automation_id": "", "class_name": "", "rect": [0, 0, 10, 10],
             "enabled": True, "visible": True, "is_password": False, "children": list(children)}
        d.update(kw)
        return d

    class Reader:
        def windows(self):
            return [{"handle": 11, "title": "Fenster A", "class_name": "Notepad", "pid": 5}, {"handle": 12, "title": "Fenster B", "class_name": "X", "pid": 6}]

        def tree(self, handle, max_depth, max_nodes, max_text, deadline):
            if handle == 99:
                raise LookupError("weg")
            if handle == 98:
                time.sleep(60)
            if handle == 97:
                raise RuntimeError("geheim " + "%(secret)s")
            if handle == 96:
                sys.exit(3)
            if handle == 95:
                return node("0", "Passwort", "Window", [node("0.0", "Kennwort", "Edit", is_password=True, value="%(secret)s")])
            if handle == 94:
                return node("0", "x" * 5000, "Window", [node("0.%%d" %% i, "k%%d" %% i, "Button") for i in range(1500)])
            if handle == 93:
                return {"runtime_id": "0"}
            return node("0", "Fenster A", "Window", [
                node("0.0", "Menue", "MenuBar", [node("0.0.0", "Datei", "MenuItem")]),
                node("0.1", "Text", "Edit", automation_id="15"),
            ])

    serve(Reader(), sys.stdin, sys.stdout)
''' % {"secret": SECRET})


@pytest.fixture()
def worker_cmd(tmp_path):
    path = tmp_path / "fake_worker.py"
    path.write_text(WORKER_SCRIPT, encoding="utf-8")
    return [sys.executable, "-u", str(path)]


@pytest.fixture()
def make(worker_cmd):
    made = []

    def build(**kw):
        from jarvis.computer.providers.pywinauto_uia import PywinautoUiaProvider
        kw.setdefault("worker_command", worker_cmd)
        kw.setdefault("call_timeout", 15.0)
        p = PywinautoUiaProvider(**kw)
        made.append(p)
        return p

    yield build
    for p in made:
        p.shutdown()


def err(fn, *a):
    with pytest.raises(ComputerError) as info:
        fn(*a)
    return info.value


# ---- Lesen ueber den Worker-Prozess -------------------------------------------------------------------------------------------------------
def test_the_provider_is_a_read_only_ui_tree_provider(make):
    p = make()
    assert isinstance(p, UiTreeProvider) and p.name == "pywinauto-uia"


def test_windows_are_listed_as_window_info(make):
    wins = make().list_windows()
    assert [(w.handle, w.title, w.class_name, w.pid) for w in wins] == [(11, "Fenster A", "Notepad", 5), (12, "Fenster B", "X", 6)]


def test_describe_returns_a_bounded_snapshot(make):
    snap = make().describe(11, UiLimits())
    assert snap.window_handle == 11 and snap.node_count == 4 and not snap.truncated
    assert snap.root.control_type is ControlType.WINDOW and snap.root.children[0].children[0].name == "Datei"


def test_find_searches_the_tree_in_the_parent(make):
    res = make().find(11, UiQuery(control_type="Edit"), UiLimits())
    assert [m.automation_id for m in res.matches] == ["15"] and not res.truncated


def test_an_unknown_window_is_window_not_found(make):
    assert err(make().describe, 99, UiLimits()).code is ErrorCode.WINDOW_NOT_FOUND


@pytest.mark.parametrize("handle", [True, "11", None, 1.5])
def test_a_bad_handle_is_rejected_before_any_process_is_started(make, handle):
    p = make(worker_command=[sys.executable, "-c", "raise SystemExit(7)"])
    assert err(p.describe, handle, UiLimits()).code is ErrorCode.INVALID_INPUT
    assert p.calls_used == 0 and not p.worker_running


def test_the_password_value_never_arrives_even_if_a_worker_sends_it(make):
    snap = make().describe(95, UiLimits())
    field = snap.root.children[0]
    assert field.is_password and field.value is None
    assert SECRET not in json.dumps(snap.info()) and SECRET not in repr(snap)


def test_oversized_trees_are_cut_to_the_limits(make):
    snap = make().describe(94, UiLimits(max_nodes=50, max_text=20))
    assert snap.node_count <= 50 and snap.truncated and len(snap.root.name) <= 20


def test_a_tree_larger_than_the_hard_maximum_never_exceeds_it(make):
    snap = make().describe(94, UiLimits(max_nodes=HARD_MAX_NODES))
    assert snap.node_count <= HARD_MAX_NODES


def test_a_malformed_tree_is_a_controlled_backend_error(make):
    assert err(make().describe, 93, UiLimits()).code in (ErrorCode.BACKEND_ERROR, ErrorCode.INVALID_INPUT)


def test_a_worker_error_message_does_not_leak_the_exception_text(make):
    e = err(make().describe, 97, UiLimits())
    assert e.code is ErrorCode.BACKEND_ERROR and SECRET not in str(e) and "geheim" not in str(e)


def test_a_crashing_worker_is_an_error_and_the_next_call_starts_a_new_one(make):
    p = make()
    assert err(p.describe, 96, UiLimits()).code is ErrorCode.BACKEND_ERROR
    assert p.describe(11, UiLimits()).node_count == 4


def test_a_hanging_worker_is_stopped_after_the_timeout(make):
    p = make(call_timeout=1.0)
    start = time.monotonic()
    e = err(p.describe, 98, UiLimits())
    assert e.code is ErrorCode.BACKEND_ERROR and "timeout" in e.message.lower() and time.monotonic() - start < 10
    assert not p.worker_running
    assert p.describe(11, UiLimits()).node_count == 4


def test_a_missing_worker_program_is_unavailable_not_a_crash(make):
    p = make(worker_command=["/nonexistent/python-xyz"])
    assert isinstance(err(p.describe, 11, UiLimits()), ComputerError)


def test_a_worker_that_never_answers_with_json_is_an_error(make):
    p = make(worker_command=[sys.executable, "-c", "print('kein json'); import time; time.sleep(5)"])
    assert err(p.list_windows).code is ErrorCode.BACKEND_ERROR


def test_one_worker_serves_all_calls_in_order(make):
    p = make()
    for _ in range(3):
        p.list_windows()
        p.describe(11, UiLimits())
    assert p.workers_started == 1


# ---- Notaus und Sitzungsbudget ---------------------------------------------------------------------------------------------------------------
def test_halt_refuses_all_calls_stops_the_worker_and_resume_allows_them_again(make):
    p = make()
    p.describe(11, UiLimits())
    assert p.worker_running
    p.halt("test")
    assert not p.worker_running
    for call in (lambda: p.describe(11, UiLimits()), lambda: p.find(11, UiQuery(), UiLimits()), p.list_windows):
        assert err(call).code is ErrorCode.FAILSAFE
    p.resume()
    assert p.describe(11, UiLimits()).node_count == 4


def test_the_session_budget_is_enforced_and_halt_resume_does_not_reset_it(make):
    p = make(max_calls=3)
    p.list_windows(); p.describe(11, UiLimits()); p.find(11, UiQuery(), UiLimits())
    assert p.calls_used == 3
    assert err(p.list_windows).code is ErrorCode.RATE_LIMITED
    p.halt(); p.resume()
    assert err(p.describe, 11, UiLimits()).code is ErrorCode.RATE_LIMITED


def test_failed_calls_also_count_against_the_budget(make):
    p = make(max_calls=2)
    err(p.describe, 99, UiLimits()); err(p.describe, 99, UiLimits())
    assert err(p.describe, 11, UiLimits()).code is ErrorCode.RATE_LIMITED


@pytest.mark.parametrize("kw", [{"max_calls": 0}, {"max_calls": 10_001}, {"call_timeout": 0}, {"call_timeout": 601}, {"max_calls": True}])
def test_invalid_provider_settings_are_rejected(kw):
    from jarvis.computer.providers.pywinauto_uia import PywinautoUiaProvider
    with pytest.raises(ComputerError):
        PywinautoUiaProvider(**kw)


def test_the_controller_halt_stops_the_ui_provider_too():
    from jarvis.computer import ComputerBackend
    from jarvis.computer.controller import ComputerController
    from jarvis.computer.providers.fake import FakeBackend

    class Stub:
        halted: list = []

        def halt(self, reason="x"): self.halted.append(reason)

        def resume(self): self.halted.append("resume")

    stub = Stub()
    stub.halted = []
    backend = FakeBackend().bundle()
    backend.ui = stub
    ctl = ComputerController(backend)
    ctl.halt("stop")
    ctl.resume()
    assert stub.halted == ["stop", "resume"]


# ---- Fabrik, fehlende Bibliothek, Standard aus ---------------------------------------------------------------------------------------------
def test_the_factory_refuses_clearly_on_other_platforms(monkeypatch):
    from jarvis.computer.providers import pywinauto_uia
    monkeypatch.setattr(pywinauto_uia.sys, "platform", "linux")
    e = err(pywinauto_uia.create_uia_provider)
    assert isinstance(e, ComputerUnavailableError) and "Windows" in e.message


def test_the_factory_names_the_extra_when_the_library_is_missing(monkeypatch):
    from jarvis.computer.providers import pywinauto_uia
    monkeypatch.setattr(pywinauto_uia.sys, "platform", "win32")
    monkeypatch.setattr(pywinauto_uia.importlib.util, "find_spec", lambda name: None)
    e = err(pywinauto_uia.create_uia_provider)
    assert isinstance(e, ComputerUnavailableError) and "uia" in e.message and "pip install" in e.message


def test_uia_is_off_by_default_in_code_and_in_the_shipped_config():
    from jarvis.config import ComputerSettings
    s = ComputerSettings()
    assert s.uia_enabled is False and 1 <= s.uia_max_calls_per_session <= 10_000 and 0 < s.uia_call_timeout <= 600
    cfg = tomllib.loads((ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8"))
    assert cfg["computer"]["uia_enabled"] is False and cfg["computer"]["enabled"] is False


def test_invalid_uia_settings_fail_the_config_validation():
    import dataclasses
    from jarvis.config import ConfigError, Settings, ComputerSettings
    for bad in ({"uia_max_calls_per_session": 0}, {"uia_call_timeout": 0.0}, {"uia_max_calls_per_session": 10_001}):
        with pytest.raises(ConfigError):
            Settings(computer=dataclasses.replace(ComputerSettings(), **bad)).validate()


def test_a_disabled_uia_setting_leaves_the_backend_without_ui():
    from jarvis.computer.factory import create_backend
    from jarvis.config import ComputerSettings
    assert create_backend(ComputerSettings(backend="fake")).ui is None


def test_an_unusable_uia_provider_does_not_stop_the_subsystem(monkeypatch, tmp_path):
    import dataclasses
    from jarvis.computer import factory
    from jarvis.config import ComputerSettings, Settings
    from jarvis.permissions import ScriptedConfirmation
    from jarvis.tools import ToolRegistry
    from computer_util import ONCE
    from secutil import make_engine

    def broken(*a, **k):
        raise ComputerUnavailableError("pywinauto fehlt: pip install -e .[uia]")

    monkeypatch.setattr(factory, "_create_uia", broken)
    engine, _sink, _ws = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE] * 5))
    settings = dataclasses.replace(Settings(), computer=ComputerSettings(enabled=True, backend="fake", uia_enabled=True))
    sub = factory.build_computer(settings, ToolRegistry(engine), engine)
    assert sub.status == "enabled" and "uia" in sub.reason.lower() and "ui" not in sub.controller.describe()["capabilities"]


def test_the_fake_backend_gets_the_fake_ui_provider_when_uia_is_enabled(tmp_path):
    import dataclasses
    from jarvis.computer import factory
    from jarvis.config import ComputerSettings, Settings
    from jarvis.permissions import ScriptedConfirmation
    from jarvis.tools import ToolRegistry
    from computer_util import ONCE
    from secutil import make_engine
    engine, _sink, _ws = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE] * 5))
    settings = dataclasses.replace(Settings(), computer=ComputerSettings(enabled=True, backend="fake", uia_enabled=True))
    sub = factory.build_computer(settings, ToolRegistry(engine), engine)
    assert sub.status == "enabled" and "ui" in sub.controller.describe()["capabilities"]


# ---- Aufbau: Extra, Import, Struktur ------------------------------------------------------------------------------------------------------
def test_pyproject_has_the_windows_only_extra_and_no_hard_dependency():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == []
    extra = data["project"]["optional-dependencies"]["uia"]
    assert len(extra) == 1 and re.fullmatch(r"pywinauto>=0\.6\.9,<0\.7; sys_platform == 'win32'", extra[0]), extra


def test_importing_jarvis_and_the_provider_module_loads_no_automation_library():
    code = ("import sys, jarvis, jarvis.computer.factory, jarvis.computer.providers.pywinauto_uia, jarvis.computer.providers.uia_worker; "
            "bad=[m for m in ('pywinauto','comtypes','pythoncom','win32api','win32gui') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def _imports_at_top_level(path: Path) -> set[str]:
    out = set()
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module.split(".")[0])
    return out


@pytest.mark.parametrize("path", [PROVIDER_FILE, WORKER_FILE])
def test_the_library_is_imported_only_lazily(path):
    assert not ({"pywinauto", "comtypes", "pythoncom", "win32api", "win32gui", "win32con", "ctypes"} & _imports_at_top_level(path))


ACTING = {"click", "click_input", "double_click", "double_click_input", "right_click_input", "type_keys", "send_keys", "set_focus", "set_edit_text",
          "set_text", "set_value", "Invoke", "invoke", "SetValue", "select", "toggle", "expand", "collapse", "scroll", "press", "hotkey", "type_text",
          "move_mouse", "drag_mouse_input", "press_mouse_input", "release_mouse_input", "SetFocus", "minimize", "maximize", "restore", "capture_as_image",
          "terminate_process"}
FORBIDDEN_TEXT = ("SendInput", "keybd_event", "mouse_event", "SetCursorPos", "PostMessage", "SendMessage", "WM_CLOSE", "Application(", "pywinauto.keyboard",
                  "pywinauto.mouse", "InvokePattern", "ValuePattern", "CurrentValue", "TerminateProcess", "taskkill", "shell=True", "os.system")


@pytest.mark.parametrize("path", [PROVIDER_FILE, WORKER_FILE])
def test_no_input_click_or_process_control_exists_in_the_provider(path):
    text = path.read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in ACTING, f"{path.name}: .{n.func.attr}()"
    for token in FORBIDDEN_TEXT:
        assert token not in text, f"{path.name}: {token}"
    assert not re.search(r"(?m)^\s*(import|from)\s+(socket|urllib|http|requests|ftplib|smtplib)\b", text)


def test_the_provider_exposes_only_reading_and_lifecycle_methods():
    from jarvis.computer.providers.pywinauto_uia import PywinautoUiaProvider
    public = {n for n in dir(PywinautoUiaProvider) if not n.startswith("_") and callable(getattr(PywinautoUiaProvider, n))}
    assert public == {"describe", "find", "list_windows", "halt", "resume", "shutdown"}


def test_the_worker_reads_no_values_and_only_the_password_flag():
    text = WORKER_FILE.read_text(encoding="utf-8")
    assert "CurrentIsPassword" in text and "window_text" not in text and ".get_value" not in text


# ---- Windows: ein echtes Fenster ---------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="UI Automation gibt es nur unter Windows; der Windows-CI-Lauf ist der Nachweis")
class TestRealWindow:
    def test_a_real_notepad_window_is_listed_described_and_found(self):
        import importlib.util
        assert importlib.util.find_spec("pywinauto") is not None, "pywinauto fehlt: pip install -e .[uia] (oder .[dev]); das ist ein Fehler, kein Skip"
        from jarvis.computer.providers.pywinauto_uia import create_uia_provider
        provider = create_uia_provider(call_timeout=60.0, max_calls=200)
        proc = subprocess.Popen(["notepad.exe"])
        try:
            deadline, hit = time.monotonic() + 60, None
            while hit is None and time.monotonic() < deadline:
                hit = next((w for w in provider.list_windows() if re.search(r"(?i)notepad|untitled", w.title)), None)
                if hit is None:
                    time.sleep(1)
            assert hit is not None, "kein Notepad-Fenster gefunden"
            snap = provider.describe(hit.handle, UiLimits(max_depth=8, max_nodes=300))
            assert snap.node_count > 3 and snap.root.rect.width > 0 and snap.root.rect.height > 0
            types = {e.control_type for e in _walk(snap.root)}
            assert types & {ControlType.EDIT, ControlType.DOCUMENT}, sorted(t.value for t in types)
            assert not any(e.is_password for e in _walk(snap.root))
            found = provider.find(hit.handle, UiQuery(control_type="Edit"), UiLimits(max_depth=8, max_nodes=300))
            found = found if found.matches else provider.find(hit.handle, UiQuery(control_type="Document"), UiLimits(max_depth=8, max_nodes=300))
            assert found.matches and all(not m.children for m in found.matches)
            assert err(provider.describe, 0x7FFFFFF0, UiLimits()).code in (ErrorCode.WINDOW_NOT_FOUND, ErrorCode.BACKEND_ERROR)
            provider.halt()
            assert not provider.worker_running
        finally:
            provider.shutdown()
            proc.terminate()               # nur das selbst gestartete Notepad-Prozess-Objekt dieses Tests


def _walk(e):
    yield e
    for c in e.children:
        yield from _walk(c)
