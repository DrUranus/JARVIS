# LLM-Budget (E6) – Stand 2026-11-12

**Standard: AUS** (`[llm_budget] enabled = false`). Dann bleibt das Provider-Objekt unverändert; kein Verhalten ändert sich.

## Was es tut
Mit `enabled = true` umhüllt `bootstrap.build_core` den LLM-Provider **einmal** mit `llm/budgeted.py`. Core, Coding-Agent, Ziele, Routing-Agent und Selbstverbesserung teilen sich diesen Wrapper
(`core.subsystems["llm_budget"]` liefert den Status: Aufrufe, Token, Kosten oder `UNKNOWN`, Ablehnungen).

Vor **jedem** Aufruf (`complete` und `complete_text` laufen über denselben Pfad):
1. Not-Aus aktiv → Ablehnung (der Riegel wird nur gelesen).
2. Plan: Ausgabe = `request.max_tokens`, sonst `llm.max_tokens`; Eingabe = **Schätzung** Zeichen/3 (aufgerundet). Die Schätzung wird nie als Verbrauch ausgewiesen.
3. `CostBudget.check`: Aufrufe, Eingabe/Ausgabe je Aufruf, geschätzte Eingabe der Sitzung, Gesamttoken der Sitzung, optional Kosten.
4. Ablehnung = `LLMError("LLM-Budget: …")` nur mit Zahlen (nie Prompt, Antwort, Schlüssel), **ein** `budget_exhausted`-Audit-Ereignis (`tool="llm"`), kein Retry, kein Ausweichen auf ein anderes Modell.

Nach dem Aufruf: meldet der Provider beide Token-Zahlen, werden sie gebucht (`record`); sonst werden die geplanten Höchstwerte als **Schätzung** gebucht (`record_estimated`), damit die Sitzungslimits auch ohne `usage` greifen. Ein fehlgeschlagener Aufruf wird ebenfalls als Schätzung gebucht (er kann gesendet und abgerechnet worden sein). Aufrufe laufen unter einer Sperre, damit gleichzeitige Aufrufer ein Limit nicht überschreiten.

## Entwicklungs-Defaults (vorläufig, vom Owner am 2026-11-12 festgelegt)
| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `max_calls` | 30 | LLM-Aufrufe je Sitzung |
| `max_output_tokens_per_call` | 2048 | geplante Ausgabe je Aufruf (ein strengeres bestehendes Limit, z. B. `llm.max_tokens` 1024, bleibt wirksam) |
| `max_input_tokens_per_call` | 50 000 | geschätzte Eingabe je Aufruf |
| `max_input_tokens_session` | 50 000 | geschätzte oder gemessene Eingabe der Sitzung |
| `max_tokens_session` | 100 000 | Eingabe + Ausgabe der Sitzung |
| `max_cost` | leer | kein Kostenlimit |
| `prices` | leer | `"modell;input_per_1k;output_per_1k"` als Text-Dezimal |

Keine automatische Erhöhung: die Grenzen sind eingefroren, es gibt kein Setzen, Zurücksetzen oder Anheben zur Laufzeit; eine neue Sitzung ist ein neues Budget.

## Geld (fail-closed)
* Unbekannte Preise werden **nie** geschätzt oder als gesichert gespeichert; ohne Eintrag in `prices` sind die Kosten `UNKNOWN`.
* Ist `max_cost` gesetzt und fehlt der Preis des Modells oder sind frühere Kosten unbekannt (z. B. kein `usage`), wird der Aufruf **abgelehnt**.
* Geldbeträge sind Text-Dezimalzahlen (kein Float); negative, nicht endliche oder über die Hartgrenze liegende Werte → `ConfigError` beim Start.

## Grenzen / nicht getan
* Kein Eingriff in PermissionEngine, X0, Audit-Format, Sicherheitsstandards oder `config/jarvis.toml`.
* Die Zeichen/3-Schätzung kann Tokens unter- oder überschätzen; sie schützt nicht vor einer Rechnung, sondern begrenzt die Zahl und Größe der Aufrufe. Ein echtes Geldlimit gilt nur mit eingetragenen Preisen.
* Windows-Nachweis: ausstehend, bis der CI-Windows-Lauf des PR grün ist.
