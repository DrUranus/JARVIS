"""WP08: Skip-Bericht (tests/support/skip_report.py). Liest die Ausgabe von `pytest -rs`, gruppiert die Gruende und vergleicht mit der Baseline (tests/support/skip_baseline.json).

Ein uebersprungener Test gilt nie als bestanden: das Werkzeug macht neue Skips sichtbar (mehr als die Baseline oder unbekannter Grund) und weist Skips, die nur die interaktive
Abnahme belegen kann, getrennt aus. Reine Textverarbeitung: kein Netzwerk, keine Plattformabhaengigkeit, keine Pytest-Ausfuehrung."""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SUPPORT = Path(__file__).resolve().parent / "support"
TOOL = SUPPORT / "skip_report.py"
BASELINE = SUPPORT / "skip_baseline.json"
spec = importlib.util.spec_from_file_location("skip_report_under_test", TOOL)
sr = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sr                                                        # noetig fuer dataclasses mit 'from __future__ import annotations'
spec.loader.exec_module(sr)                                                       # type: ignore[union-attr]

SAMPLE = """\
.......s...ss.......
=========================== short test summary info ============================
SKIPPED [1] tests\\test_security_paths.py:110: POSIX symlink semantics
SKIPPED [5] tests/test_security_paths_windows.py:93: NTFS junctions / reparse points exist only on Windows (the POSIX symlink tests cover the other platforms)
SKIPPED [2] tests\\test_control_center_native_windows.py:116: JARVIS_NATIVE_GUI=1 fehlt: nur auf einem interaktiven Windows-Desktop (nicht bestanden, nur uebersprungen)
SKIPPED [1] tests\\test_research_extract_backend.py:158: could not import 'trafilatura': No module named 'trafilatura'
SKIPPED [3] tests\\test_computer_x11_real.py:82: needs Linux and Xvfb (virtual X11 display)
12 passed, 12 skipped in 3.21s
"""


def test_lines_are_parsed_with_their_multiplicity():
    items = sr.parse(SAMPLE)
    assert sum(i.count for i in items) == 12 and len(items) == 5
    assert items[1].count == 5 and items[1].path.endswith("test_security_paths_windows.py") and items[1].line == 93


def test_the_summary_line_is_read_and_cross_checked():
    assert sr.summary_counts(SAMPLE) == (12, 12)
    assert sr.summary_counts("nothing here") is None
    rep = sr.build_report(SAMPLE.replace("12 skipped", "99 skipped"), "windows", {"windows": {"max_skipped": 100}, "known_reasons": []})
    assert any("Summenzeile" in w for w in rep.warnings)


def test_reasons_are_grouped_into_categories_and_interactive_skips_are_flagged():
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    rep = sr.build_report(SAMPLE, "windows", base)
    cats = rep.by_category
    assert cats["interaktiv (nur PC-Abnahme #186/G9)"] == 2
    assert cats["plattformbedingt"] == 1 + 5 + 3
    assert cats["optionale Bibliothek fehlt"] == 1
    assert rep.unknown_reasons == []


def test_more_skips_than_the_baseline_fail_and_equal_or_fewer_pass():
    base = {"windows": {"max_skipped": 12}, "known_reasons": json.loads(BASELINE.read_text(encoding="utf-8"))["known_reasons"]}
    assert sr.build_report(SAMPLE, "windows", base).exit_code(strict=True) == 0
    base["windows"]["max_skipped"] = 11
    rep = sr.build_report(SAMPLE, "windows", base)
    assert rep.exit_code(strict=True) == 1 and any("Baseline" in w for w in rep.warnings)


def test_unknown_reasons_fail_only_in_strict_mode():
    text = SAMPLE + "SKIPPED [1] tests/test_new.py:5: gerade erst ausgedacht\n"
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base["windows"]["max_skipped"] = 999
    rep = sr.build_report(text, "windows", base)
    assert rep.unknown_reasons == ["gerade erst ausgedacht"]
    assert rep.exit_code(strict=False) == 0 and rep.exit_code(strict=True) == 2


def test_the_baseline_file_is_valid_and_documents_its_sources():
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert base["schema"] == 1
    assert base["windows"]["max_skipped"] == 45 and base["linux"]["max_skipped"] == 119          # gezaehlte Skips; der Checkout-Skip steht separat (WP08b)
    assert all(base[p]["source"] for p in ("windows", "linux"))
    for entry in base["known_reasons"]:
        flagged = entry.get("checkout_dependent") is True
        assert set(entry) == ({"pattern", "category", "checkout_dependent", "max"} if flagged else {"pattern", "category"}) and entry["category"] in sr.CATEGORIES
        assert not flagged or ("origin/main" in entry["pattern"] and entry["max"] == 1)                       # nur dieser eine, begruendete Grund ist Checkout-abhaengig
    import re
    for entry in base["known_reasons"]:
        re.compile(entry["pattern"])                                              # jedes Muster ist gueltig


def test_the_real_windows_log_reasons_are_all_known():
    """Die Gruende aus dem echten Windows-Lauf (PR #229, Lauf 42987707150: 5270 bestanden, 46 uebersprungen) sind alle in der Baseline erfasst."""
    reasons = [
        "could not import 'playwright': No module named 'playwright'",
        "playwright fehlt: Browser-E2E nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)",
        "needs git and a POSIX shell script", "POSIX symlinks", "POSIX symlink semantics", "no X11 on Windows", "POSIX shell scripts", "POSIX shell script",
        "kein origin/main in diesem Checkout", "needs Linux and Xvfb (virtual X11 display)",
        "JARVIS_NATIVE_GUI=1 fehlt: nur auf einem interaktiven Windows-Desktop (nicht bestanden, nur uebersprungen)",
        "link creation needs a privilege on Windows; the CI Windows run is the platform proof", "could not import 'trafilatura': No module named 'trafilatura'",
        "POSIX mode bits; the Windows equivalent is the ACL tests below", "on Windows the real Win32 layer is used (see the win_ tests)",
        "descendant discovery uses /proc (Linux only; Windows is untested)"]
    text = "\n".join(f"SKIPPED [1] tests\\\\x.py:{i}: {r}" for i, r in enumerate(reasons, 1))
    rep = sr.build_report(text, "windows", json.loads(BASELINE.read_text(encoding="utf-8")))
    assert rep.unknown_reasons == []


def test_garbage_input_gives_an_empty_report_not_an_exception():
    for text in ("", "\x00\x01", "SKIPPED [x] foo", "SKIPPED [1] kein Pfad", "x" * 100_000):
        rep = sr.build_report(text, "linux", json.loads(BASELINE.read_text(encoding="utf-8")))
        assert rep.total == 0 and rep.exit_code(strict=True) in (0, 2)


def test_main_prints_a_report_and_returns_the_exit_code(tmp_path, capsys):
    f = tmp_path / "pytest.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    assert sr.main([str(f), "--platform", "windows", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "12" in out and "interaktiv" in out
    assert sr.main([str(f), "--platform", "windows", "--baseline", str(tmp_path / "missing.json")]) == 3     # Baseline fehlt: kein stilles Gruen


def test_the_tool_only_reads_text():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {x.name.split(".")[0] for x in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert not (mods & {"socket", "http", "urllib", "requests", "httpx", "subprocess", "shutil", "sqlite3", "threading", "asyncio"}), mods


# ---- WP08b: ein Skip haengt vom Checkout ab (origin/main vorhanden oder nicht) -------------------------------------------------------------------
CHECKOUT = "SKIPPED [1] tests/test_computer_uia_tools.py:384: kein origin/main in diesem Checkout\n"


def _base(max_skipped: int) -> dict:
    return {"linux": {"max_skipped": max_skipped}, "known_reasons": json.loads(BASELINE.read_text(encoding="utf-8"))["known_reasons"]}


def test_the_origin_main_skip_is_reported_separately_and_does_not_hide_other_skips():
    """In PR-Checkouts fehlt origin/main (der Test wird uebersprungen), in einem Checkout mit origin/main laeuft er: das ist die Differenz 119 <-> 120, kein neuer Skip."""
    text = SAMPLE.replace("12 skipped", "13 skipped") + CHECKOUT
    rep = sr.build_report(text, "linux", _base(12))
    assert rep.total == 13 and rep.checkout_dependent == 1 and rep.counted == 12
    assert rep.exit_code(strict=True) == 0 and not any("Baseline" in w for w in rep.warnings)
    assert "checkout" in sr.format_report(rep).lower()


def test_an_additional_unexplained_skip_still_fails_even_if_the_checkout_skip_is_present():
    text = SAMPLE.replace("12 skipped", "14 skipped") + CHECKOUT + "SKIPPED [1] tests/test_x.py:3: POSIX symlink semantics\n"
    rep = sr.build_report(text, "linux", _base(12))
    assert rep.counted == 13 and rep.exit_code(strict=True) == 1


def test_the_checkout_skip_may_appear_at_most_as_often_as_allowed():
    text = SAMPLE.replace("12 skipped", "15 skipped") + CHECKOUT.replace("[1]", "[3]")
    rep = sr.build_report(text, "linux", _base(12))
    assert rep.checkout_dependent == 1 and rep.counted == 14 and rep.exit_code(strict=True) == 1          # der Rest zaehlt normal


def test_the_baseline_separates_the_checkout_dependent_skip_from_the_counted_limits():
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    entry = next(e for e in base["known_reasons"] if "origin/main" in e["pattern"])
    assert entry.get("checkout_dependent") is True and entry.get("max") == 1
    assert base["linux"]["max_skipped"] == 119 and base["windows"]["max_skipped"] == 45         # gezaehlte Skips OHNE den Checkout-Skip (CI PR-Laeufe: 120 bzw. 46 gesamt)
    assert "origin/main" in (base["linux"]["source"] + base["windows"]["source"])
