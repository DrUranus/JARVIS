"""Reproduzierbarer Vergleich lokaler Spracherkennungsmodelle (faster-whisper) auf IDENTISCHEN Audiodaten.

Ablauf (nur lokal, kein Netzwerk, keine Cloud-Aufrufe, keine echten Benutzeraufnahmen ohne dein Zutun):
  1) Korpus erzeugen:   python scripts/stt/benchmark.py prepare
       Synthetische Sprache aus scripts/stt/corpus.json mit der Windows-Sprachausgabe (Hedda de-DE / Zira en-US) -> data/stt-corpus/*.wav + *.txt (Referenz).
       ACHTUNG: synthetisch. Das sind keine echten Dialekte/Akzente/Umgangssprache; Ergebnisse dafuer werden nie erfunden.
       Eigene Aufnahmen (rechtmaessig, von dir): <name>.wav (16 kHz mono) + <name>.txt (Referenz) in data/stt-corpus/real/ ablegen; sie bleiben lokal.
  2) Messen:            python scripts/stt/benchmark.py run --model base=C:/JARVIS-Test/models/whisper-base --model small=C:/.../whisper-small [--device cpu] [--compute int8]
       Jedes Modell laeuft in einem eigenen Prozess (saubere Ladezeit- und Speichermessung).
  3) Ergebnis: reports/stt/<zeit>.json und eine Tabelle auf der Konsole.
Messgroessen: Ladezeit, erste Transkription (kalt), Median warm, Echtzeitfaktor (RTF), Spitzen-Arbeitsspeicher des Prozesses, WER und CER (Gross-/Kleinschreibung und
Satzzeichen ignoriert), Anteil erkannter kritischer Woerter (Befehls-Semantik: z. B. lies/loesche), je Kategorie. Zusaetzlich WER nach der behutsamen
Nachbearbeitung (jarvis.voice.postprocess)."""
from __future__ import annotations

import argparse
import ctypes
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "scripts" / "stt" / "corpus.json"
WAV_DIR = ROOT / "data" / "stt-corpus"
REPORTS = ROOT / "reports" / "stt"
HINTS = "Begriffe: JARVIS, NEXUS, Windows, PowerShell, Ordner."
PS_SPEAK = r"""
param([string]$TextFile, [string]$Out, [string]$Voice)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($Voice)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($Out, $fmt)
$s.Speak([IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8))
$s.Dispose()
"""


# ---- Metriken -----------------------------------------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", text.lower().replace("ß", "ss"), flags=re.UNICODE)
    return " ".join(text.split())


def _edit(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer_counts(ref: str, hyp: str) -> tuple[int, int]:
    """(Wortfehler, Referenzwoerter): fuer die gewichtete (mikro) WER ueber den ganzen Korpus; kurze Saetze dominieren sonst den Mittelwert."""
    r, h = _norm(ref).split(), _norm(hyp).split()
    return _edit(r, h), max(1, len(r))


def wer(ref: str, hyp: str) -> float:
    r, h = _norm(ref).split(), _norm(hyp).split()
    return _edit(r, h) / max(1, len(r))


def cer(ref: str, hyp: str) -> float:
    r, h = _norm(ref).replace(" ", ""), _norm(hyp).replace(" ", "")
    return _edit(list(r), list(h)) / max(1, len(r))


def critical_ok(critical: list[str], hyp: str) -> tuple[int, int]:
    hn = _norm(hyp)
    return sum(1 for c in critical if _norm(c) in hn), len(critical)


# ---- Korpus erzeugen ------------------------------------------------------------------------------------------------------------------------
def prepare() -> int:
    items = json.loads(CORPUS.read_text(encoding="utf-8"))["items"]
    WAV_DIR.mkdir(parents=True, exist_ok=True)
    (WAV_DIR / "real").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ps1 = Path(tmp) / "speak.ps1"
        ps1.write_text(PS_SPEAK, encoding="utf-8")
        for it in items:
            wav = WAV_DIR / f"{it['id']}.wav"
            txt_in = Path(tmp) / "in.txt"
            txt_in.write_text(it.get("tts_text", it["text"]), encoding="utf-8")
            voice = {"Hedda": "Microsoft Hedda Desktop", "Zira": "Microsoft Zira Desktop"}[it["voice"]]
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-TextFile", str(txt_in), "-Out", str(wav), "-Voice", voice],
                           check=True, capture_output=True, timeout=120)
            (WAV_DIR / f"{it['id']}.txt").write_text(it["text"], encoding="utf-8")
            print(f"{it['id']:12} {it['category']:20} {wav.stat().st_size // 1024:5d} KB")
    print(f"{len(items)} synthetische Dateien in {WAV_DIR}")
    return 0


def load_items(include_real: bool) -> list[dict]:
    meta = {i["id"]: i for i in json.loads(CORPUS.read_text(encoding="utf-8"))["items"]}
    out = []
    for wav in sorted(WAV_DIR.glob("*.wav")):
        if wav.stem in meta:
            out.append({**meta[wav.stem], "wav": str(wav), "synthetic": True})
    if include_real:
        for wav in sorted((WAV_DIR / "real").glob("*.wav")):
            ref = wav.with_suffix(".txt")
            if ref.exists():
                out.append({"id": "real-" + wav.stem, "category": "echt", "lang": "de", "text": ref.read_text(encoding="utf-8").strip(), "critical": [], "wav": str(wav), "synthetic": False})
    return out


def read_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as w:
        rate, raw = w.getframerate(), w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False), np.arange(len(audio)), audio).astype(np.float32)
    return audio


# ---- Worker (ein Modell, eigener Prozess) -------------------------------------------------------------------------------------------------------
def _peak_ws_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return -1.0
    return round(pmc.PeakWorkingSetSize / 1048576, 1)


def worker(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from jarvis.voice.postprocess import normalize_transcript
    from faster_whisper import WhisperModel
    items = load_items(args.real)
    t0 = time.perf_counter()
    model = WhisperModel(args.model_dir, device=args.device, compute_type=args.compute, local_files_only=True, cpu_threads=args.threads)
    load_s = time.perf_counter() - t0
    rows = []
    for k, it in enumerate(items):
        audio = read_wav(it["wav"])
        dur = len(audio) / 16000
        lang = None if args.language == "auto" else (args.language if args.language else it["lang"])
        t1 = time.perf_counter()
        segments, info = model.transcribe(audio, language=lang, vad_filter=True, initial_prompt=HINTS if args.hints else None, beam_size=args.beam)
        hyp = " ".join(s.text.strip() for s in segments).strip()
        sec = time.perf_counter() - t1
        ok, total = critical_ok(it.get("critical", []), hyp)
        rows.append({"id": it["id"], "category": it["category"], "synthetic": it["synthetic"], "audio_s": round(dur, 2), "seconds": round(sec, 3), "cold": k == 0,
                     "ref": it["text"], "hyp": hyp, "lang": getattr(info, "language", None), "wer": round(wer(it["text"], hyp), 4), "cer": round(cer(it["text"], hyp), 4),
                     "wer_post": round(wer(it["text"], normalize_transcript(hyp)), 4), "critical_ok": ok, "critical_total": total,
                     "w_err": wer_counts(it["text"], hyp)[0], "w_ref": wer_counts(it["text"], hyp)[1], "w_err_post": wer_counts(it["text"], normalize_transcript(hyp))[0]})
    print(json.dumps({"model_dir": args.model_dir, "device": args.device, "compute": args.compute, "language": args.language or "per-item", "hints": args.hints, "beam": args.beam, "threads": args.threads,
                      "load_s": round(load_s, 2), "peak_ws_mb": _peak_ws_mb(), "rows": rows}, ensure_ascii=False))
    return 0


# ---- Orchestrierung ---------------------------------------------------------------------------------------------------------------------------
def summarize(res: dict) -> dict:
    rows = res["rows"]
    warm = [r for r in rows if not r["cold"]]
    audio = sum(r["audio_s"] for r in rows)
    out = {"load_s": res["load_s"], "peak_ws_mb": res["peak_ws_mb"], "cold_first_s": rows[0]["seconds"], "median_warm_s": round(statistics.median(r["seconds"] for r in warm), 3),
           "rtf": round(sum(r["seconds"] for r in rows) / max(audio, 1e-9), 3), "wer": round(statistics.mean(r["wer"] for r in rows), 4), "wer_micro": round(sum(r["w_err"] for r in rows) / sum(r["w_ref"] for r in rows), 4),
           "wer_micro_post": round(sum(r["w_err_post"] for r in rows) / sum(r["w_ref"] for r in rows), 4),
           "cer": round(statistics.mean(r["cer"] for r in rows), 4), "wer_post": round(statistics.mean(r["wer_post"] for r in rows), 4),
           "critical": f"{sum(r['critical_ok'] for r in rows)}/{sum(r['critical_total'] for r in rows)}", "by_category": {}}
    for cat in sorted({r["category"] for r in rows}):
        sub = [r for r in rows if r["category"] == cat]
        out["by_category"][cat] = {"n": len(sub), "wer": round(statistics.mean(r["wer"] for r in sub), 4), "cer": round(statistics.mean(r["cer"] for r in sub), 4)}
    return out


def run(args: argparse.Namespace) -> int:
    if not list(WAV_DIR.glob("*.wav")):
        print("Kein Korpus: zuerst `python scripts/stt/benchmark.py prepare`", file=sys.stderr)
        return 2
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = {}
    for spec in args.model:
        label, _, path = spec.partition("=")
        cmd = [sys.executable, "-I", __file__, "worker", "--model-dir", path, "--device", args.device, "--compute", args.compute]
        if args.language is not None:
            cmd += ["--language", args.language]
        if args.hints:
            cmd.append("--hints")
        if args.real:
            cmd.append("--real")
        cmd += ["--beam", str(args.beam), "--threads", str(args.threads)]
        print(f"== {label}: {path} ({args.device}/{args.compute})", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env={**__import__("os").environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"})
        if proc.returncode != 0:
            print(f"   FEHLER: {proc.stderr.strip()[-400:]}", file=sys.stderr)
            results[label] = {"error": proc.stderr.strip()[-400:]}
            continue
        res = json.loads(proc.stdout.strip().splitlines()[-1])
        res["summary"] = summarize(res)
        results[label] = res
        s = res["summary"]
        print(f"   Laden {s['load_s']}s | kalt {s['cold_first_s']}s | warm-Median {s['median_warm_s']}s | RTF {s['rtf']} | RAM-Spitze {s['peak_ws_mb']} MB | "
              f"WER {s['wer_micro']:.3f} (Mittel je Datei {s['wer']:.3f}; nach Nachbearb. {s['wer_micro_post']:.3f}) | CER {s['cer']:.3f} | kritische Woerter {s['critical']}", flush=True)
    out = REPORTS / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    out.write_text(json.dumps({"corpus": "synthetisch (Windows-TTS) + optional echt", "device": args.device, "compute": args.compute, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Ergebnis: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    r = sub.add_parser("run")
    r.add_argument("--model", action="append", required=True, help="label=Verzeichnis (mehrfach)")
    r.add_argument("--device", default="cpu")
    r.add_argument("--compute", default="int8")
    r.add_argument("--language", default=None, help="de | en | auto (Standard: Sprache je Eintrag)")
    r.add_argument("--hints", action="store_true", help="Stichworthinweise (initial_prompt) verwenden")
    r.add_argument("--real", action="store_true", help="eigene Aufnahmen aus data/stt-corpus/real/ einbeziehen")
    r.add_argument("--beam", type=int, default=5, help="Beam-Groesse (faster-whisper-Standard 5; 1 = gierig, deutlich schneller)")
    r.add_argument("--threads", type=int, default=0, help="CPU-Threads (0 = Bibliotheksstandard)")
    w = sub.add_parser("worker")
    w.add_argument("--model-dir", required=True)
    w.add_argument("--device", default="cpu")
    w.add_argument("--compute", default="int8")
    w.add_argument("--language", default=None)
    w.add_argument("--hints", action="store_true")
    w.add_argument("--real", action="store_true")
    w.add_argument("--beam", type=int, default=5)
    w.add_argument("--threads", type=int, default=0)
    a = ap.parse_args()
    return {"prepare": lambda: prepare(), "run": lambda: run(a), "worker": lambda: worker(a)}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
