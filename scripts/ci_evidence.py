"""Maschinenlesbarer CI-Nachweis aus einem JUnit-Bericht (nur Standardbibliothek, keine Netzwerkzugriffe).

Aufruf: python scripts/ci_evidence.py <junit.xml> <ausgabe.json> [--baseline scripts/ci_skip_baseline.json]
Kontext (Commit, Lauf, Job, PR) kommt aus Umgebungsvariablen, nie aus untrusted Texten wie PR-Titel oder Branch-Namen.
Exitcode 0 nur bei status == "passed". Der Nachweis ist ein Hilfsmittel; ein Merge-Gate muss die GitHub-Checks und die
Commit-SHA unabhaengig pruefen und darf sich nie allein auf dieses Artefakt stuetzen.
"""
import argparse
import datetime
import json
import os
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1


def classify_skip(message: str, patterns: list[str]) -> bool:
    return any(re.search(p, message) for p in patterns)


def parse_report(path: str, patterns: list[str]) -> dict | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    expected, unexpected = [], []
    for case in root.iter("testcase"):
        ident = f"{case.get('classname')}::{case.get('name')}"
        skipped = case.find("skipped")
        if case.find("failure") is not None or case.find("error") is not None:
            counts["failed"] += 1
        elif skipped is not None:
            counts["skipped"] += 1
            message = (skipped.get("message") or "")[:200]
            (expected if classify_skip(message, patterns) else unexpected).append({"test": ident, "reason": message})
        else:
            counts["passed"] += 1
    return {**counts, "expected_skips": expected, "unexpected_skips": unexpected}


def git_head() -> tuple[str | None, str | None]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    return run("rev-parse", "HEAD"), run("rev-parse", "HEAD^2")


def build_evidence(junit: str, patterns: list[str], env: dict, head: str | None, head_parent2: str | None) -> dict:
    result = parse_report(junit, patterns)
    pr_head = env.get("PR_HEAD_SHA") or None
    problems: list[str] = []
    tests_outcome = env.get("TEST_OUTCOME", "")
    if result is None:
        problems.append("Testbericht fehlt oder ist nicht lesbar")
        result = {"passed": 0, "failed": 0, "skipped": 0, "expected_skips": [], "unexpected_skips": []}
    if tests_outcome != "success":
        problems.append(f"Testschritt endete mit '{tests_outcome or 'unbekannt'}'")
    if env.get("EVENT_NAME") == "pull_request" and (not pr_head or head_parent2 != pr_head):
        problems.append("getesteter Merge-Commit passt nicht zum PR-Head")
    if result["passed"] == 0:
        problems.append("kein bestandener Test")
    if result["unexpected_skips"]:
        problems.append(f"{len(result['unexpected_skips'])} unerwartete Skips")
    if result["failed"] > 0:
        status = "failed"
    elif problems:
        status = "failed" if result["unexpected_skips"] and len(problems) == 1 else "error"
    else:
        status = "passed"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "problems": problems,
        "tested_commit": head or env.get("GITHUB_SHA"),
        "pr_head_sha": pr_head,
        "pr_number": int(env["PR_NUMBER"]) if env.get("PR_NUMBER", "").isdigit() else None,
        "event": env.get("EVENT_NAME"),
        "repository": env.get("GITHUB_REPOSITORY"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": env.get("GITHUB_RUN_ID"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "job": env.get("GITHUB_JOB"),
        "matrix": env.get("MATRIX_ID"),
        "os": env.get("RUNNER_OS") or platform.system(),
        "python": platform.python_version(),
        "tests_outcome": tests_outcome,
        "passed": result["passed"],
        "failed": result["failed"],
        "skipped": result["skipped"],
        "expected_skips": len(result["expected_skips"]),
        "unexpected_skips": result["unexpected_skips"],
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trust_note": "Hilfsnachweis. Fuer ein Merge-Gate zaehlen allein die GitHub-Checks auf der PR-Head-SHA.",
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("junit")
    ap.add_argument("output")
    ap.add_argument("--baseline", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ci_skip_baseline.json"))
    args = ap.parse_args(argv)
    with open(args.baseline, encoding="utf-8") as fh:
        baseline = json.load(fh)["platforms"]
    runner_os = (os.environ.get("RUNNER_OS") or platform.system()).lower()
    patterns = baseline["windows" if runner_os.startswith("win") else "linux"]
    head, parent2 = git_head()
    evidence = build_evidence(args.junit, patterns, dict(os.environ), head, parent2)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, ensure_ascii=False)
    print(f"CI-Nachweis: {evidence['status']} | passed {evidence['passed']} failed {evidence['failed']} skipped {evidence['skipped']}"
          f" (unerwartet: {len(evidence['unexpected_skips'])}) | Commit {evidence['tested_commit']}")
    for problem in evidence["problems"]:
        print(f"::error::{problem}")
    for skip in evidence["unexpected_skips"]:
        print(f"::error::Unerwarteter Skip: {skip['test']} - {skip['reason']}")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
