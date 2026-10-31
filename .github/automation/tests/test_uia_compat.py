"""Isolierter Windows-Kompatibilitaetstest fuer pywinauto 0.6.9 (ci/uia-compat, Workflow uia-compat.yml).

Hier wird nur geprueft, was ohne Windows und ohne pywinauto pruefbar ist: die Pins samt Hashes, die Auswertung von Aufloesung/Lizenzen/.pth-Dateien, die Regeln des
Testskripts (nur lesend, nie ein Skip, jede Abweichung schlaegt an) und die Sicherheitsregeln des Workflows. Die eigentliche Kompatibilitaet belegt nur der CI-Lauf unter Windows.
Kein Netzwerk, keine Installation, kein Produktionscode."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / "ci" / "uia-compat"
WORKFLOW = ROOT / ".github" / "workflows" / "uia-compat.yml"

PINS = {"pywinauto": "0.6.9", "six": "1.17.0", "comtypes": "1.4.17", "pywin32": "312"}
HASHES = {      # SHA-256 der Pruefung vom 2026-10-31 (docs/integrations/windows-uia.md)
    "pywinauto": {"5924b3072864a1d730c5546bbeb17cf4063ba518b618dbc5e43c18276c7c9356"},
    "six": {"4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274"},
    "comtypes": {"4e0a221dde2c589b82977bed802efd71cd5eb67a380347b732e02735e597f586"},
    "pywin32": {"c53e878d15a1c44788082bfe712a905433473aa38f86375b7cf8b45e3acbaaf9", "a4dd3a848290ef724347b19f301045831d8e802fa4464f491b98b1e0a081432e"},
}


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"uia_compat_{name}", CI / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def resolve():
    return load("resolve_check")


@pytest.fixture(scope="module")
def files():
    return load("check_files")


@pytest.fixture(scope="module")
def uia():
    return load("check_uia")


@pytest.fixture(scope="module")
def failed():
    return load("assert_failed")


REQ = (CI / "requirements.txt").read_text(encoding="utf-8") if (CI / "requirements.txt").exists() else ""


# ---- Pins ---------------------------------------------------------------------------------------------------------------------------------
def test_requirements_pin_exactly_the_four_reviewed_packages_with_their_reviewed_hashes(resolve):
    parsed = resolve.parse_requirements(REQ)
    assert {n: v for n, (v, _) in parsed.items()} == PINS
    assert {n: h for n, (_, h) in parsed.items()} == HASHES
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for _, hs in parsed.values() for h in hs)
    assert "--index-url" not in REQ and "--extra-index-url" not in REQ and "git+" not in REQ and "http" not in REQ     # nur das Standard-Register, nie eine andere Quelle


@pytest.mark.parametrize("text", ["pywinauto>=0.6.9 --hash=sha256:" + "a" * 64, "pywinauto==0.6.9", "pywinauto==0.6.9 --hash=md5:abc", "-e .", "pywinauto @ https://x/y.whl"])
def test_unpinned_or_unhashed_requirements_are_rejected(resolve, text):
    with pytest.raises(ValueError):
        resolve.parse_requirements(text)


# ---- Aufloesung ---------------------------------------------------------------------------------------------------------------------------
def report(*overrides, drop=(), extra=()):
    items = []
    for name, ver in PINS.items():
        if name in drop:
            continue
        sha = sorted(HASHES[name])[0]
        items.append({"metadata": {"name": name, "version": ver}, "is_yanked": False,
                      "download_info": {"url": f"https://files.pythonhosted.org/packages/x/{name}-{ver}-py3-none-any.whl", "archive_info": {"hashes": {"sha256": sha}}}})
    for fn in overrides:
        fn(items)
    items += list(extra)
    return {"version": "1", "install": items}


def test_the_exact_reviewed_resolution_passes(resolve):
    assert resolve.verify(report(), REQ) == []


@pytest.mark.parametrize("make,needle", [
    (lambda: report(drop=("six",)), "fehlt"),
    (lambda: report(extra=[{"metadata": {"name": "evil", "version": "1"}, "is_yanked": False, "download_info": {"url": "x.whl", "archive_info": {"hashes": {"sha256": "0" * 64}}}}]), "unerwartet"),
    (lambda: report(lambda i: i[0]["metadata"].update(version="9.9.9")), "Version"),
    (lambda: report(lambda i: i[0]["download_info"].update(url="https://files.pythonhosted.org/x/pywinauto-0.6.9.tar.gz")), "Wheel"),
    (lambda: report(lambda i: i[1]["download_info"]["archive_info"]["hashes"].update(sha256="f" * 64)), "Hash"),
    (lambda: report(lambda i: i[1].update(is_yanked=True)), "zurueckgezogen"),
    (lambda: {"version": "1"}, "Bericht"),
])
def test_any_deviation_in_the_resolution_is_reported(resolve, make, needle):
    problems = resolve.verify(make(), REQ)
    assert problems and any(needle in p for p in problems), problems


# ---- Lizenzen, .pth-Dateien -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("license_field,classifiers,files_,ok", [
    ("BSD 3-clause", ["License :: OSI Approved :: BSD License"], ["LICENSE.txt"], True),
    ("MIT", [], [], True),                                                                 # Metadaten genuegen, die fehlende Datei wird nur gemeldet
    ("", ["License :: OSI Approved :: MIT License"], [], True),
    ("", [], ["COPYING"], True),
    ("", [], [], False),                                                                   # gar keine Lizenzangabe
    ("GPL-3.0", [], ["LICENSE"], False),
    ("MIT", ["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"], [], False),
    ("AGPL-3.0-only", [], [], False),
    ("LGPL-2.1", [], ["COPYING"], False),                                                  # auch schwaches Copyleft braucht eine Besitzerentscheidung
])
def test_license_findings(files, license_field, classifiers, files_, ok):
    findings = files.license_problems("pkg", license_field, classifiers, files_)
    assert (findings == []) is ok, findings


def test_only_the_known_pywin32_path_file_is_accepted(files):
    good = {"pywin32.pth": ["# .pth file for the PyWin32 extensions", "win32", "win32\\lib", "pythonwin", "# And some hackery to deal with environments where the post_install script",
                            "# isn't run.", "import pywin32_bootstrap"]}          # genau der Inhalt, den der Windows-Lauf vom 2026-10-31 zeigte (kleingeschriebenes 'pythonwin')
    assert files.pth_problems(good) == []
    assert files.pth_problems({"pywin32.pth": ["Pythonwin"]}) == []                  # Gross-/Kleinschreibung ist egal
    assert files.pth_problems({"pywin32.pth": ["pythonwin2"]})                       # aber nur diese Pfade
    assert files.pth_problems({}) == []
    assert files.pth_problems({"evil.pth": ["import os; os.system('x')"]})
    assert files.pth_problems({"pywin32.pth": ["win32", "import os"]})
    assert files.pth_problems({**good, "other.pth": ["win32"]})


# ---- Testskript -------------------------------------------------------------------------------------------------------------------------------
def test_the_script_is_read_only_and_never_skips(uia):
    src = (CI / "check_uia.py").read_text(encoding="utf-8")
    assert uia.forbidden_calls(src) == []
    assert not re.search(r"(?i)\bskip|xfail|pytest\.mark|importorskip|sys\.exit\(0\)\s*#", src)
    for sample in ("w.click_input()", "e.type_keys('a')", "p.kill()", "e.invoke()", "e.set_edit_text('x')", "os.system('taskkill')", "proc.terminate()", "send_keys('x')"):
        assert uia.forbidden_calls(sample), sample


@pytest.mark.parametrize("expected,vi,ok", [
    ("3.13", (3, 13, 17), True), ("3.14", (3, 14, 0), True),
    ("3.14", (3, 13, 17), False), ("3.13", (3, 14, 0), False), (None, (3, 13, 0), False), ("", (3, 13, 0), False), ("3.1", (3, 13, 0), False),
])
def test_python_version_must_match_the_expectation_exactly(uia, expected, vi, ok):
    problem = uia.python_problem(expected, vi)
    assert (problem is None) is ok, problem


def test_window_matching_needs_a_real_title_match(uia):
    assert uia.match_title(["", "Taskbar", "Untitled - Notepad"], r"(?i)untitled|notepad") == "Untitled - Notepad"
    assert uia.match_title(["", "Taskbar"], r"(?i)notepad") is None
    assert uia.match_title([], r".*") is None
    assert uia.match_title(["Notepad"], r"^NoSuchWindow$") is None


def test_the_overall_result_fails_when_any_blocking_check_fails(uia):
    ok = {"name": "a", "ok": True, "blocking": True, "detail": ""}
    assert uia.verdict([ok, dict(ok, name="b")]) == 0
    assert uia.verdict([ok, dict(ok, name="b", ok=False)]) == 1
    assert uia.verdict([ok, dict(ok, name="b", ok=False, blocking=False)]) == 0        # nur Hinweis
    assert uia.verdict([]) == 1                                                        # kein Ergebnis ist nie ein Erfolg


def test_the_script_fails_cleanly_without_the_library(uia):
    results = uia.run_checks({"EXPECT_PYTHON": f"{sys.version_info[0]}.{sys.version_info[1]}", "UIA_COMPAT_NO_START": "1"})
    names = {r["name"]: r for r in results if not r["ok"]}
    assert {"versions", "imports"} <= set(names), results                                   # ohne installierte Pakete: klare Fehler, kein Absturz
    assert uia.verdict(results) == 1


def test_negative_run_assertion_helper(failed):
    results = [{"name": "python_version", "ok": False, "blocking": True}, {"name": "window", "ok": True, "blocking": True}, {"name": "note", "ok": False, "blocking": False}]
    assert failed.check(results, ["python_version"], exact=True) is True
    assert failed.check(results, ["window"], exact=True) is False
    assert failed.check(results, ["python_version", "window"], exact=True) is False
    assert failed.check(results, ["python_version"], exact=False) is True
    assert failed.check([], ["python_version"], exact=False) is False


# ---- Workflow ---------------------------------------------------------------------------------------------------------------------------
def test_the_workflow_is_isolated_read_only_and_hash_pinned():
    text = WORKFLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["permissions"] == {"contents": "read"} and "secrets." not in text and "pull_request_target" not in text
    triggers = doc[True]
    assert set(triggers) == {"pull_request", "workflow_dispatch"}
    assert set(triggers["pull_request"]["paths"]) == {"ci/uia-compat/**", ".github/workflows/uia-compat.yml"}        # laeuft nur, wenn dieser Test selbst geaendert wird
    (job,) = doc["jobs"].values()
    assert job["runs-on"] == "windows-latest" and job["strategy"]["fail-fast"] is False
    assert [str(v) for v in job["strategy"]["matrix"]["python"]] == ["3.13", "3.14"]
    assert job["timeout-minutes"] <= 30
    assert "--require-hashes" in text and "--only-binary=:all:" in text and "--dry-run" in text
    assert "-r ci/uia-compat/requirements.txt" in text
    assert not re.search(r"pip install [^\n]*(pywinauto|comtypes|pywin32|six)[=<>~ ]", text.replace("requirements.txt", ""))      # nie ein freier Paketname
    assert "pip install -e" not in text and "pip install ." not in text                                                 # JARVIS selbst wird nicht installiert
    assert "pyproject.toml" not in text
    assert "persist-credentials: false" in text and "upload-artifact" in text


def test_the_workflow_proves_that_the_test_really_fails():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("assert_failed.py") >= 3                                       # falsches Fenster, falsche Python-Version, fehlende Bibliothek
    assert "EXPECT_PYTHON" in text and "UIA_COMPAT_NO_START" in text
    assert "check_files.py" in text and "resolve_check.py" in text and "pip check" in text
    steps = " ".join(s.get("name", "") for s in yaml.safe_load(text)["jobs"]["uia-compat"]["steps"])
    for word in ("Aufloesung", "Lizenz", "Gegenprobe"):
        assert word in steps, word


def test_nothing_else_in_the_repository_depends_on_the_new_test():
    for path in (ROOT / "pyproject.toml", ROOT / ".github/workflows/pr-tests.yml", ROOT / ".github/workflows/tests.yml"):
        assert "uia-compat" not in path.read_text(encoding="utf-8") and "pywinauto" not in path.read_text(encoding="utf-8"), path.name
