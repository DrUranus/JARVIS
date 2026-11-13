"""V2.1 Mission 8: der Benchmark laeuft (kleinste Groesse) und liefert vollstaendige, plausible Messdaten. Keine Schwellen: Zielwerte legt der Owner fest."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v21_bench_under_test", ROOT / "scripts" / "bench" / "v21_bench.py")
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


def test_every_case_runs_small_and_reports_time_memory_and_conditions(tmp_path, capsys):
    out = tmp_path / "bench.json"
    assert bench.main(["--runs", "1", "--scale", "0.02", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["cases"]) == set(bench.CASES) and data["environment"]["cpus"] and data["conditions"]["llm"] == "mock"
    for name, c in data["cases"].items():
        assert c["n"] >= 1 and c["median_s"] >= 0 and c["min_s"] <= c["median_s"] <= c["max_s"] and c["peak_python_mb"] >= 0, name
    assert data["cases"]["orchestrator_10_agents_threads"]["info"]["peak_running"] <= 10


def test_invalid_arguments_are_refused_and_the_script_uses_no_network():
    assert bench.main(["--runs", "0"]) == 2 and bench.main(["--scale", "1000"]) == 2
    text = (ROOT / "scripts" / "bench" / "v21_bench.py").read_text(encoding="utf-8")
    for bad in ("socket", "urllib", "requests", "subprocess", "http.client"):
        assert bad not in text, bad


def test_build_core_case_leaves_no_open_log_file_behind():
    """Windows (CI): eine noch geoeffnete jarvis.log blockiert das Loeschen des Temp-Ordners (WinError 32). Plattformunabhaengig geprueft: nach dem Fall haengt kein FileHandler mehr am Logger."""
    import logging
    bench.case_build_core(1)
    assert not [h for h in logging.getLogger("jarvis").handlers if isinstance(h, logging.FileHandler)]
