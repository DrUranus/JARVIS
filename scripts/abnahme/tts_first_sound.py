"""Nur Windows: Messhilfe fuer die Windows-TTS-Abnahme (S4).

--mode wav     : Softwareanteil. Misst je Lauf die Zeit von WindowsTTS.speak() bis die WAV-Datei fertig ist (PowerShell-Start + Synthese) und die Audiodauer.
                 Das ist eine Obergrenze der Vorlaufzeit, KEIN hoerbarer Ton und KEINE Messung der Audio-Hardware.
--mode audible : Hoerbarer Anteil. Das Skript spricht ueber das Standardgeraet, du drueckst Enter, sobald du den ERSTEN TON hoerst. Die Reaktionszeit (ca. 0,2-0,3 s) ist nicht
                 abgezogen und wird im Protokoll als Fehlerquelle genannt. Lauf 1 (Kaltstart) wird getrennt ausgewiesen.
Nutzt nur vorhandenen Code (jarvis.voice.windows_tts.WindowsTTS), schreibt nur eine JSON-Datei, installiert nichts, aendert keine Konfiguration.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

SENTENCE = "Dies ist ein deutscher Testsatz mit Umlauten: Größe, Übung und Fähre."


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def measure_wav(runs: int) -> list[dict]:
    from jarvis.voice.windows_tts import WindowsTTS
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(runs):
            target = Path(tmp) / f"m{i}.wav"
            t0 = time.perf_counter()
            WindowsTTS(wave_file=str(target)).speak(SENTENCE)
            dt = (time.perf_counter() - t0) * 1000
            out.append({"run": i + 1, "synth_ready_ms": round(dt, 1), "audio_s": round(_wav_seconds(target), 2), "cold": i == 0})
    return out


def measure_audible(runs: int) -> list[dict]:
    from jarvis.voice.windows_tts import WindowsTTS
    out = []
    for i in range(runs):
        input(f"\nLauf {i + 1}/{runs}: Enter druecken -> Sprachausgabe startet; dann ERNEUT Enter, sobald du den ersten Ton hoerst ...")
        tts = WindowsTTS()
        t0 = time.perf_counter()
        worker = threading.Thread(target=tts.speak, args=(SENTENCE,), daemon=True)
        worker.start()
        input()
        dt = (time.perf_counter() - t0) * 1000
        tts.stop()
        worker.join(timeout=5)
        out.append({"run": i + 1, "to_first_sound_ms_incl_reaction": round(dt, 1), "cold": i == 0})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("wav", "audible"), required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", default="abnahme-v2/04-tts-latenz.json")
    a = ap.parse_args()
    if sys.platform != "win32":
        print("Nur Windows (Windows PowerShell + System.Speech).")
        return 2
    rows = measure_wav(a.runs) if a.mode == "wav" else measure_audible(a.runs)
    key = "synth_ready_ms" if a.mode == "wav" else "to_first_sound_ms_incl_reaction"
    warm = [r[key] for r in rows if not r["cold"]] or [rows[0][key]]
    result = {"mode": a.mode, "runs": rows, "median_warm_ms": round(statistics.median(warm), 1), "cold_ms": rows[0][key], "python": platform.python_version(), "platform": platform.platform(),
              "note": "wav: Obergrenze der Vorlaufzeit, kein hoerbarer Ton. audible: Reaktionszeit des Menschen (ca. 200-300 ms) ist enthalten. Kein Zielwert (Owner-Zahl G5/G7 offen): nur MEASURED."}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
