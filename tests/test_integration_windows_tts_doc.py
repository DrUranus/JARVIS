"""WP05a: Vertragstest fuer die Pruefdatei docs/integrations/windows-tts.md. Reine Textpruefung: nichts wird ausgefuehrt, kein Netzwerk, keine Plattformabhaengigkeit.

Haelt fest, was die Pruefung zusagt (Schema, vorlaeufige Entscheidung, Sicherheitsregeln fuer den spaeteren Provider) und dass `system_tts.py` weiterhin keinen Windows-Standard kennt,
solange Teil B nicht freigegeben und umgesetzt ist."""
from pathlib import Path

from test_integration_docs import check_integration_doc

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "integrations" / "windows-tts.md"


def text() -> str:
    return DOC.read_text(encoding="utf-8")


def section(name: str) -> str:
    out, on = [], False
    for line in text().splitlines():
        if line.startswith("## "):
            on = line[3:].strip() == name
            continue
        if on:
            out.append(line)
    return "\n".join(out)


def test_the_check_file_satisfies_the_integration_schema():
    assert check_integration_doc(text()) == []


def test_the_decision_is_preliminary_until_windows_evidence_exists():
    decision = section("Entscheidung").strip().splitlines()[0].strip().lower()
    assert decision == "nicht nehmen"
    for must in ("Runner-Test", "Injektionstest", "Hörprobe", "E8"):
        assert must in section("Entscheidung") or must in text()


def test_the_security_rules_for_the_later_provider_are_written_down():
    sec = section("Sicherheitshinweise")
    assert "Standardeingabe" in sec and "-Command -" in sec and "verboten" in sec        # stdin als Daten, nie als Code
    assert "shell=False" in sec and "Argument" in sec
    assert "-ExecutionPolicy Bypass" in sec and "Kein" in sec                              # Richtlinie wird nicht umgangen
    assert "-NoProfile" in sec and "-NonInteractive" in sec and "UTF-8" in sec


def test_the_check_states_that_nothing_was_installed_or_executed():
    head = text()[:600]
    assert "Nichts wurde installiert" in head and "nicht gestartet" in head
    assert "Keine Python-Pakete" in section("Transitive Abhaengigkeiten")
    assert "nicht anwendbar" in section("Pinning mit Hash").lower()


def test_cloud_tts_stays_excluded_and_no_windows_provider_exists_yet():
    assert "ausgeschlossen" in text()
    src = (ROOT / "src" / "jarvis" / "voice" / "system_tts.py").read_text(encoding="utf-8")
    assert "powershell" not in src.lower() and "System.Speech" not in src
    factory = (ROOT / "src" / "jarvis" / "voice" / "factory.py").read_text(encoding="utf-8")
    assert 'register_tts("windows"' not in factory                                          # Teil B ist nicht freigegeben
    assert not (ROOT / "src" / "jarvis" / "voice" / "windows_tts.py").exists()
