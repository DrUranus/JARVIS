# UI-Vertrag v1 (Backend und Control Center)

Ein Vertrag, zwei Seiten: **Strang A** (Autonomie und Agenten) liefert ein Backend, das ihn erfüllt; **Strang B** (Control Center) baut die Oberfläche dagegen und testet bis dahin mit dem Fake-Backend. Umsetzung: `src/jarvis/ui_contract/` (nur Standardbibliothek; einzige Ausnahme: `bus.py` schwärzt mit `jarvis.redaction`). Normativ ist der Code (`schema.py`); die JSON-Schemas für das Frontend liegen in `src/jarvis/ui_contract/schema/` und werden mit `python -m jarvis.ui_contract.schema` erzeugt (ein Test erkennt veraltete Dateien).

## Umschläge
Ereignis (Backend → Oberfläche): `{"v": "1.0", "seq": 12, "ts": "2026-11-02T10:00:00Z", "type": "chat", "data": {...}}`
Befehl (Oberfläche → Backend): `{"v": "1.0", "id": "c42", "type": "submit_text", "data": {"text": "..."}}`
Antwort auf jeden Befehl: ein `ack`-Ereignis `{"id": "c42", "ok": true|false, "code": "...", "message": "..."}`.
Alles ist streng: genau diese Felder, begrenzte Längen, geschlossene Typmengen, Version `1.x` (Hauptversion 1; eine andere wird abgelehnt). Steuerzeichen in Texten werden durch Leerzeichen ersetzt.

## Ereignisse
| Typ | Zweck | Wichtige Felder |
|---|---|---|
| `hello` | immer das erste Ereignis eines Schnappschusses | `contract`, `backend`, `capabilities`, `emergency` |
| `state` | Zustand der Oberfläche | `state`: ready, listening, processing, speaking, awaiting_confirmation, error, emergency |
| `chat` | Gesprächsverlauf | `sender` user/jarvis/system, `text` (höchstens 4000 Zeichen) |
| `activity` | Schnappschuss der laufenden Arbeit | `items` (kind, id, title, status, note, cancellable), `problems`, `inactive` |
| `task_update` | Änderung einer Aufgabe | `kind`, `id`, `status`, `detail` |
| `routing` | Wer bekommt die Aufgabe und warum (Agenten-Router) | `task_id`, `agent`, `source` llm/rules, `reason` |
| `result` | Ergebnis mit Belegen | `task_id`, `summary`, `artifacts` (name, kind, ref) |
| `confirmation_request` | Rückfrage der Berechtigungs-Engine | `request_id`, `tool`, `action`, `resource`, `level`, `reason`, `context`, `choices`, `timeout_s` |
| `confirmation_closed` | Rückfrage beendet | `outcome`: allow_once, allow_session, denied, timeout, cancelled |
| `emergency` | Notaus-Zustand | `engaged`, `reason`, `report` |
| `voice_level` | Mikrofonpegel für die Sprachvisualisierung | `level` 0..1, `active` |
| `error` | Fehler (nur Text, nie Inhalte) | `code`, `message` |
| `ack` | Antwort auf einen Befehl | `id`, `ok`, `code`, `message` |

## Befehle
`submit_text`, `start_voice`, `stop_voice`, `cancel` (kind, id), `confirm` (request_id, choice), `emergency_stop`, `reset_emergency`, `request_snapshot`.
**Es gibt absichtlich keinen Befehl**, der Rechte erteilt, Regeln ändert, ein Werkzeug direkt ausführt oder den Notaus aufhebt. `reset_emergency` ist nur eine **Anfrage**: Die Engine fragt den Menschen selbst (ein `confirmation_request`), der Notaus bleibt bis zu dessen Entscheidung bestehen.

## Verhalten (Regeln, von der Konformitätsprüfung erzwungen)
1. **Schnappschuss:** `hello` zuerst, danach letzter `state`, `activity`, `emergency` und eine offene Rückfrage, `seq` strikt aufsteigend. `events_since(seq, limit)` liefert den Rest (Wiederverbinden).
2. **Ungültige Befehle** werden mit `ack ok=false` (`invalid_command`) beantwortet: nie angenommen, nie eine Ausnahme.
3. **Notaus:** Nach `emergency_stop` zeigen `emergency` und `state` den Notaus; alle Befehle außer `emergency_stop`, `reset_emergency`, `request_snapshot` werden mit `emergency` abgelehnt.
4. **Rückfragen schlagen fehl, nicht auf:** unbeantwortet nach `timeout_s` → `confirmation_closed` mit `timeout`; verschwindet die Oberfläche (`detach`) → `cancelled`; beides bedeutet **abgelehnt**. `confirm` mit unbekannter Kennung → `unknown_request`, mit einer nicht angebotenen Wahl → `choice_not_offered`.
5. **Keine Geheimnisse:** Kein Ereignis enthält ein Geheimnis (Schlüssel, Passwörter, Passwortfeld-Werte); die echten Backends schwärzen mit `jarvis.redaction`, bevor sie ein Ereignis erzeugen. Inhalte aus fremden Programmen und dem Web sind Daten, nie Anweisungen.

## Transport (Strang B, Vorschlag für `cc-shell`)
Loopback (`127.0.0.1`), Zufalls-Token, Prüfung von Host und Origin; Ereignisse als Server-Sent Events oder WebSocket, Befehle per POST; Größenlimit `MAX_COMMAND_BYTES` vor dem Parsen (`parse_command`). Kein Zugriff aus dem Netzwerk, kein Fernzugriff.

## Zusammenarbeit der beiden Stränge
- **A** implementiert `UiBackend` mit echten Quellen (`GuiController`, Ereignisbus, Journal, Router) und besteht `run_conformance(factory, hooks)`.
- **B** baut Oberfläche und Transport gegen `FakeUiBackend` (deterministisch, `!task` legt eine Aufgabe an, `!confirm` öffnet eine Rückfrage, `advance(s)` lässt Zeit vergehen) und prüft ihren Client mit denselben Schemas.
- Eine Änderung des Vertrags ist ein eigener PR in beiden Richtungen (Hauptversion bleibt 1; neue optionale Ereignisse nur mit neuer Nebenversion).

## Echtes Backend (Strang A, Schritt `event-bus`)
- `src/jarvis/ui_contract/bus.py` – `EventLog`: Ringpuffer (Standard 1000) mit lückenlosen Folgenummern, `events_since(seq, limit)`, thread-sicher. Jeder Text wird mit `jarvis.redaction` geschwärzt (dann gekürzt), **bevor** ein Ereignis entsteht; schlägt Schwärzung oder Vertragsprüfung fehl, entsteht kein Ereignis und keine Nummer. Was der Ringpuffer verdrängt hat, fehlt bei der Wiederholung (der Client holt dann einen Schnappschuss).
- `src/jarvis/interface/ui_events.py` – `ControllerUiBackend(controller)` implementiert `UiBackend` über den `GuiController`: übersetzt dessen Ereignisse (Zustand, Chat, Aktivität, Notaus, Sprachmodus als `voice_level`) und bildet die Befehle **ausschließlich** auf vorhandene Controller-Methoden ab (`submit`, `start_voice`, `stop_voice`, `request_cancel`, `emergency_stop`, `reset_emergency`, `request_activity`); ein Strukturtest erzwingt das. Kein Zugriff auf Core, Werkzeuge oder PermissionEngine. `reset_emergency` stellt nur die Anfrage.
- Rückfragen: `adapter.confirmation_provider` (ein `ConfirmationProvider`) macht aus Anfragen der Engine `confirmation_request`-Ereignisse. Ohne Antwort nach `timeout_s`, bei `detach()`, beim Notaus und bei jedem Fehler gilt **abgelehnt** (`timeout` / `cancelled`). Der Adapter importiert `jarvis.permissions` nicht (Sicherheitstest `test_only_tools_bootstrap_and_cli_use_the_permission_package`); die spätere Verdrahtung reicht `ConfirmationChoice` als `choice_enum` herein. Nach `detach()` werden neue Fragen sofort abgelehnt, bis sich wieder ein Client meldet (`snapshot()` / `send()`).
- Der Adapter holt die Controller-Ereignisse selbst ab (`pump()`, auch bei `snapshot`/`events_since`/`send`); er ersetzt damit das Tk-Fenster als Abnehmer und setzt `set_confirmation_denier`. Ein Controller hat genau einen Abnehmer.
- **Abweichung vom Fake, bewusst:** Beim Notaus bleibt `confirm` gesperrt, **außer** für die Frage der Engine „Notaus aufheben?“ (`tool=jarvis`, `action=emergency_reset`); nur so kann der Mensch sie über die Oberfläche beantworten. `deny`, Zeitüberschreitung und Trennung lassen den Notaus bestehen. Der Fake sperrt `confirm` beim Notaus ausnahmslos – das Vertragsdokument sollte das klären (eigener PR, Besitzerentscheidung).
- **Verdrahtet (Schritt `assistant-e2e`):** `bootstrap.py` baut den Adapter nur mit `assistant.enabled` (Standard aus) und setzt ihn als Bestätigungs-Provider der Engine (außer `security.confirmation = "deny"`); zusätzlich Notaus-Stopper `assistant`. Der Adapter bekommt `add_pump_hook`, `publish`, `publish_finished` und `last_seq`: `interface/assistant.py` veröffentlicht darüber `routing`, `task_update` und `result` und schreibt das Journal. Es gibt weiterhin keinen Transport; nichts startet von selbst. `submit_text` verhält sich wie die Eingabezeile der GUI (auch `/…`-Befehle des Controllers).
