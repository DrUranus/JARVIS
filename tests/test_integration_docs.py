"""Pruefschema fuer externe Bibliotheken/Werkzeuge (docs/INTEGRATIONS.md).

Jede Datei docs/integrations/*.md muss alle Pflichtfelder (Abschnitte `## <Feld>` mit nicht leerem Inhalt) und eine gueltige Entscheidung enthalten.
Gibt es keine solche Dateien, sind die Dateitests leer (trivial gruen); die Gegenproben unten beweisen, dass fehlende Felder trotzdem anschlagen.
Reine Textpruefung: kein Netzwerk, kein Produktionscode, keine Plattformabhaengigkeit.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INTEGRATIONS_DIR = DOCS / "integrations"
SCHEMA = DOCS / "INTEGRATIONS.md"

REQUIRED_FIELDS = [
    "Name und Zweck",
    "Lizenz (Wortlaut)",
    "Version und Datum",
    "Pflege",
    "Python- und Windows-Kompatibilitaet",
    "Transitive Abhaengigkeiten",
    "Sicherheitshinweise",
    "Datenabfluss",
    "Pinning mit Hash",
    "Lizenzausschluss (AGPL/GPL)",
    "Entscheidung",
    "Pruefung (Datum und Quelle)",
]
DECISIONS = ("nehmen", "nicht nehmen")


def check_integration_doc(text: str) -> list[str]:
    """Liefert die Liste der Verstoesse (leer = Datei erfuellt das Schema)."""
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    problems = []
    for field in REQUIRED_FIELDS:
        if field not in sections:
            problems.append(f"Pflichtfeld fehlt: {field}")
        elif not sections[field].strip():
            problems.append(f"Pflichtfeld leer: {field}")
    decision = sections.get("Entscheidung", "").strip()
    if decision:
        first = decision.splitlines()[0].strip().strip("*`").lower()
        if first not in DECISIONS:
            problems.append("Entscheidung muss mit 'nehmen' oder 'nicht nehmen' beginnen")
    return problems


def make_doc(skip: str | None = None, empty: str | None = None, decision: str = "nehmen") -> str:
    parts = ["# Beispiel\n"]
    for field in REQUIRED_FIELDS:
        if field == skip:
            continue
        body = "" if field == empty else (decision if field == "Entscheidung" else "Angabe")
        parts.append(f"## {field}\n{body}\n")
    return "\n".join(parts)


DOC_FILES = sorted(INTEGRATIONS_DIR.glob("*.md")) if INTEGRATIONS_DIR.is_dir() else []


def test_integration_files_are_complete():
    """Ohne Dateien trivial gruen (kein Skip); jede vorhandene Datei muss das Schema erfuellen."""
    problems = {p.name: check_integration_doc(p.read_text(encoding="utf-8")) for p in DOC_FILES}
    assert {name: probs for name, probs in problems.items() if probs} == {}


def test_complete_document_passes():
    assert check_integration_doc(make_doc()) == []
    assert check_integration_doc(make_doc(decision="nicht nehmen")) == []


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_field_is_detected(field):
    assert any(field in p for p in check_integration_doc(make_doc(skip=field)))


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_empty_field_is_detected(field):
    assert any(field in p for p in check_integration_doc(make_doc(empty=field)))


@pytest.mark.parametrize("decision", ["vielleicht", "nehmen | nicht nehmen", "nicht"])
def test_invalid_decision_is_detected(decision):
    assert check_integration_doc(make_doc(decision=decision))


def test_schema_document_describes_every_field():
    text = SCHEMA.read_text(encoding="utf-8")
    for field in REQUIRED_FIELDS:
        assert f"## {field}" in text, field
    for decision in DECISIONS:
        assert decision in text
    assert "AGPL" in text and "GPL" in text
