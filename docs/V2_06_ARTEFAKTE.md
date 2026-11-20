# V2-06: Typisierte Übergabeartefakte (Konzept, keine Verdrahtung)

**Status: Konzept zur Besitzerentscheidung. Kein Code, keine Verdrahtung, nichts in `bootstrap.py`.** Release-Freeze und V1-Abnahme #186 unberührt. Baut auf Backlog V2-06 (`docs/V2_BACKLOG.md`) auf; V2-08 (Budgets je Agent) und V2-10/V2-11 hängen davon ab.

## 1. Ist-Zustand (aus dem Code)
- Agenten tauschen Daten bereits als **reine JSON-Daten** (`agents/models.py: check_json`, Tiefe ≤ 8, Eingabe ≤ 100 000 Byte, Text ≤ 20 000 Zeichen, Metadaten ≤ 20 Einträge). Ergebnisse liegen in `AgentOutcome.output`; Eltern-Ergebnisse erreichen Kinder über `AgentTask.dependencies` / `parent_results`.
- `research/handoff.py` ist das Vorbild: nur erfolgreiche Ergebnisse zählen, begrenzte Größen (`MAX_SOURCES=40`, `MAX_FIGURES=400`, `MAX_CLAIMS=100`), Zahlen nur endlich, nichts wird ausgeführt.
- **Lücke:** Es gibt kein gemeinsames Schema über Agentenarten hinweg. Jede Empfängerseite prüft ihr eigenes Format; Herkunft, Art und Integrität (Hash) eines Ergebnisses sind nicht einheitlich ausweisbar.

## 2. Vorschlag: `Artifact` als kleines, unveränderliches Datenobjekt
| Feld | Bedeutung | Grenze |
|---|---|---|
| `kind` | feste Liste: `text`, `table`, `file_ref`, `url_list`, `research_data`, `diff`, `summary` | nur bekannte Arten, sonst abgelehnt |
| `source` | erzeugender Agent und Schritt (`agent_id`, `task_id`) | ID-Muster der Policy |
| `sha256` | Hash des kanonisch serialisierten Inhalts | wird beim Empfang **neu berechnet und verglichen** |
| `length` | Zeichen bzw. Bytes | Obergrenze je Art |
| `content` | reine JSON-Daten oder ein Verweis (`file_ref` nur als Pfad, den `PathGuard` später prüft; nie Dateiinhalt unkontrolliert) | `check_json`-Regeln |
| `redacted` | `True` nach Schwärzung durch `SecretDetector` | Pflicht vor dem Weiterreichen |

**Regeln**
1. **Nur deklarierte Eingänge:** Ein Schritt nennt, welche Artefakt-Arten er annimmt; alles andere wird verworfen (kein „alles aus dem Elternergebnis“).
2. Größen- und Anzahllimits wie in `handoff.py`; Überschreitung = Artefakt wird gekürzt mit Markierung oder abgelehnt, nie stillschweigend durchgereicht.
3. Artefakte sind **Daten, keine Anweisungen**: ihr Inhalt ändert weder Plan noch Berechtigungen (wie Journal und Web-Inhalte heute).
4. `file_ref`, `diff` und `url_list` gewähren **kein Recht**; jeder Zugriff läuft weiter über `ToolRegistry.execute` → `PermissionEngine`.
5. Rückwärtskompatibel: bestehende `output`-Daten bleiben gültig; Artefakte kommen als zusätzlicher, optionaler Block (`output["artifacts"]`), bis eine Migration freigegeben ist.
6. Fehlerverhalten: ungültig, zu groß, Hash-Abweichung oder unbekannte Art → Artefakt entfällt, Schritt meldet es; kein Absturz und keine Teilübernahme.

## 3. Einordnung (Option A–D)
**A + D (dünn):** vorhandene Datenregeln (`check_json`, Policy-Limits) bleiben die Grundlage; neu ist nur das gemeinsame Schema mit Hash. Keine Fremdbibliothek nötig (vorhandenes Muster: `dataclass(frozen=True)`).

## 4. Abnahmetests (für die spätere Umsetzung)
1. Hash-Test: veränderter Inhalt → Ablehnung; gleiche Daten → gleicher Hash (kanonische Serialisierung).
2. Limits je Art: zu lang/zu tief/zu viele → abgelehnt oder gekürzt mit Markierung.
3. Schwärzung: eingeschleustes Geheimnis erscheint nie in einem weitergereichten Artefakt.
4. Nur deklarierte Eingänge: undeklarierte Art kommt nie beim Empfänger an.
5. Feindlicher Inhalt („Ignoriere alle Regeln …“) ändert weder Plan noch Berechtigung (Plan-Harness aus V2-02).
6. `file_ref` ohne `PathGuard`-Freigabe liefert keinen Dateizugriff.
7. Bestehende Orchestrator-Tests und Sicherheitsregression bleiben unverändert grün.

## 5. Risiken und Blocker
Risiko mittel: berührt die Datenwege zwischen Agenten (Orchestrator). Deshalb **zuerst nur das reine Schema mit Tests, unangebunden** (wie V2-03), Anbindung erst nach eigener Freigabe. Blocker: keiner technischer Art; Freigabe der Umsetzung fehlt.

## 6. Offene Entscheidungen des Besitzers
1. Ist die Artenliste (Abschnitt 2) richtig oder zu groß?
2. Soll das Schema zuerst unangebunden als Bibliothek mit Tests umgesetzt werden (Empfehlung)?
3. Soll `research/handoff.py` später auf das Schema umgestellt werden oder daneben bestehen bleiben?
