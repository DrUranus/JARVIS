# Phase 14 "Maximum Autonomy": Bestand, Sicherheitsgrenzen und pruefbare Teilziele

Stand: nach Phase 11 (GUI), Teilziel 1 (gemeinsamer Notaus) und Teilziel 2 (Sichtbarkeit laufender Arbeit; Windows-Lauf 39220035919, Commit 8f0b2dd: 434 passed / 4 skipped) - **Teilziel 1 abgeschlossen**: Windows-Runner-Lauf 39153347774 (Commit 85b036f, 415 passed / 4 skipped nur POSIX-Symlinks; alle 17 Fenstertests, 39 Notaus-Tests und 123 Engine-Tests liefen und bestanden), Linux-Regression gruen. Offene Grenzen siehe unten; die naechsten Teilziele sind nicht begonnen. Dieses Dokument beschreibt, was von Phase 14 heute **wirklich** im Code ist, welche Grenzen die Autonomie schon begrenzen, und schlaegt
**pruefbare Teilziele** vor. Es fuehrt keine neue Autonomie ein; jedes Teilziel braucht vor der Umsetzung eine ausdrueckliche Freigabe.

## Was von Phase 14 existiert

Nur **kontrolliertes LLM-Replanning** der Goal Engine (`goals/planner.py`, `goals/policy.py`, Commit `d4fcb92`, Config `goals.replanning`, README-Abschnitt
"Kontrolliertes Replanning"). Alles andere unter "Maximum Autonomy" (Hintergrundziele, Selbststart, mehrere Ziele ohne Rueckfrage, Fern-/Zeitsteuerung) ist **nicht
implementiert** und nirgends spezifiziert (weder im Repository noch in der lesbaren Sitzungshistorie).

## Grenzen, die Autonomie heute begrenzen (belegt in Code/Config)

| Grenze | Wo | Wirkung |
|---|---|---|
| Alles standardmaessig aus | `config/jarvis.toml`: `agents.enabled`, `goals.enabled`, `goals.replanning`, `computer/browser/coding.enabled` = false | nichts laeuft ohne ausdrueckliches Einschalten |
| Eine Kontrollstelle | `ToolRegistry.execute` -> `PermissionEngine` (`permissions/`) | jede Tool-Aktion: GREEN automatisch, YELLOW fragt, RED immer abgelehnt; `security.mode = "lockdown"` erlaubt nur GREEN |
| Keine Rueckfrage moeglich = Ablehnung | `security.confirmation = "deny"`; `GUIConfirmationProvider` lehnt bei Fehler/Timeout/Schliessen ab | autonome Laeufe koennen YELLOW nicht selbst freigeben |
| Audit fail-closed | `security.audit_strict = true` | ist das Audit-Log nicht schreibbar, werden nicht-GREEN-Aktionen abgelehnt |
| Harte Limits fuer Ziele | `goals.max_steps` (hart 50), `max_attempts_per_step` (hart 5), `goal_timeout_seconds`, `step_timeout_seconds`, `max_active_goals` | begrenzte Laufzeit und Breite |
| Agenten-Limits | `agents.max_concurrent`, `task_timeout_seconds`, `tool_call_limit`, `cancel_grace_seconds` | ein haengender Agent wird als FAILED markiert, nie als gestoppt behauptet |
| Replanning begrenzt | `goals.replanning`: hoechstens 2 Versuche je Ziel, nur nach wiederholbaren Fehlern, nie nach Berechtigungsablehnung/Abbruch/Timeout; Kandidat darf keine Faehigkeit/Tools/Agenten hinzufuegen und wird wie jeder Plan validiert | das Modell strukturiert nur um |
| Notaus je Subsystem | `computer`, `browser`, `coding`: `halt()`/`resume()`; Ziele und Agenten: `cancel()` | einzeln erreichbar (CLI `/computer stop`, `/browser halt`, `/coding halt`, `/goal cancel`); das GUI-Fenster ruft `halt` beim Schliessen waehrend laufender Arbeit |
| **Gemeinsamer Notaus (Teilziel 1, umgesetzt)** | `permissions/emergency.py` (`EmergencyStop`), Latch in `PermissionEngine.emergency`, Verdrahtung `bootstrap.register_emergency_components`, CLI `/notaus`, GUI-Knopf | siehe Abschnitt "Gemeinsamer Notaus" |
| Selbstaenderung gesperrt | Phase 15 ist ein deaktivierter Vorschlagsworkflow; `ExecutionGuard` ist immer gesperrt | keine Selbstmodifikation, keine Sandbox |

## Luecken (keine Behauptung von Sicherheit)

- Ein einzelner `core.handle`-Aufruf laesst sich nicht unterbrechen.
- Gesamtbudget (Teilziel 4) deckt Tool-Aufrufe und Laufzeit ab, **nicht Kosten/Token**; es ist standardmaessig aus und wird nur in der Konfiguration beim Start eingeschaltet.
- Windows-Prozesskontrolle ist Eindaemmung, keine Isolation (siehe README Phase 15).

## Gemeinsamer Notaus (Teilziel 1) - umgesetzt

Ein Latch in der `PermissionEngine` (der einzigen Kontrollstelle) plus Stopper je Komponente. `engage()` setzt den Latch sofort (kleines Lock, keine E/A, wartet auf keine Komponente - geht auch, wenn eine Anfrage haengt); danach stoppen alle Komponenten nebenlaeufig unter einer harten Frist (Standard 5 s). Solange er aktiv ist, verweigert die Engine **jede** Anfrage (auch GREEN), kein Ausfuehrungs-Scope oeffnet sich (eine kurz vorher erteilte Freigabe ist ungueltig), `JarvisCore.handle`, `create_goal/run_goal/create_repair/run_repair` lehnen ab. Aufheben nur per `reset`: die Engine fragt ueber den `ConfirmationProvider` (nur *Einmal erlauben* gilt, kein Sitzungsrecht); ohne Provider oder mit `security.confirmation = "deny"` ist ein Aufheben im laufenden Prozess nicht moeglich. Das Aufheben ist kein Tool: kein Tool-, Agenten- oder Zielcode kann den Notaus ausloesen oder aufheben (Strukturtest). Der Notaus ist nicht persistent: ein Neustart des Prozesses beginnt ohne ihn.

Integrationspruefung (Linux, laufendes Programm per Skript, Commit 60970d7): Einstiegspunkte, die `core.handle` umgingen, liessen waehrend des Notaus noch `core.plan` (legte einen Task an und rief das LLM), `core.forget` (loeschte eine Erinnerung), das CLI-`/voice` (haette das Mikrofon geoeffnet) und `/improve` zu - behoben und getestet. Komponenten ohne eigenen Stopper (`research`, `business`, `finance`, `self_improvement`, `memory`, `voice`) haben nichts Laufendes: Research/Business/Finance sind Agenten der Orchestrierung (durch deren Abbruch und den Latch abgedeckt), Self-Improvement ist ein deaktivierter Vorschlagsworkflow ohne Ausfuehrung.

Bedienung: CLI `/notaus`, `/notaus status`, `/notaus reset`; GUI: roter Knopf *NOTAUS* (kein Rueckfragedialog, der Latch ist sofort gesetzt) und *Notaus aufheben ...* (Bestaetigungsdialog der Engine). Kein Knopf ohne die zentrale Schnittstelle (keine reine Anzeige).

| Komponente | Wirkung | Garantie |
|---|---|---|
| Alle Tool-Aufrufe, `core.handle`, `core.plan`/`chat`, Gedaechtnis-Aenderungen (`remember`/`forget`), neue Ziele/Reparaturen, CLI `/voice`, `/improve` (ausser `list`/`show`) | sofort verweigert | **sofort**, durch den Latch bzw. die Einstiegspruefung (lesende Befehle wie `/tasks`, `/permissions`, `/audit`, `/memory` bleiben nutzbar) |
| `computer`, `browser`, `coding` | `halt()`: weitere Schritte werden verweigert; `coding` bricht einen laufenden Testlauf ab (`abort_running`) | sofort fuer weitere Schritte; ein Testprozess wird ueber den Provider beendet (unter Windows beendet der Coding-Provider nur den Wurzelprozess - bekannte Einschraenkung) |
| Ziele, Agenten-Tasks, Reparaturlaeufe | `cancel` fuer alle nicht beendeten | **kooperativ**: *requested* - der Agent muss den Abbruch bemerken; Agenten ohne Abbruchunterstuetzung werden als *failed* ("nicht abbrechbar") gemeldet |
| GUI | offene Bestaetigungen abgelehnt, Eingabe gesperrt, Sprachmodus beendet nach der laufenden Aufnahme (hoechstens `voice.max_record_seconds`) | die Wiedergabe laesst sich nicht unterbrechen |
| Laufende `core.handle`-/LLM-Anfrage | **nicht unterbrechbar**; sie findet nur alle Tool-Aufrufe verweigert vor | nur als *requested* gemeldet |
| Bereits ausgefuehrte externe Aktionen (Klicks, getippter Text, gestartete Programme, gesendete Anfragen, geschriebene Dateien) | **werden nicht rueckgaengig gemacht und nicht als beendet gemeldet** | keine |

Der Bericht nennt jede Komponente mit *stopped*, *requested*, *nothing*, *failed* oder *timeout*; nur "alle stopped/nothing" heisst *vollstaendig*. Ein Stopper, der einen Fehler wirft oder die Frist ueberschreitet, macht den Notaus *unvollstaendig* (sichtbar im Chat/CLI und im Audit-Log als `emergency_stop`). Der CLI-Sprachmodus blockiert das Terminal und kennt keinen Notaus; er endet mit dem Wort *exit*. Ein Notaus ist keine Sandbox und beweist keine Isolation.

## Sichtbarkeit laufender Arbeit (Teilziel 2) - umgesetzt

GUI-Reiter *Status*, Abschnitt "Laufende Arbeit": nicht beendete Ziele (`core.list_goals`), Agenten-Tasks (`orchestrator.list`), Reparaturlaeufe (`core.list_repairs`) und gespeicherte Plaene (`core.tasks.open_tasks`; ein Plan ist nur ein Eintrag, nichts fuehrt ihn aus) mit Status, Kurztext und einem Knopf *Abbrechen* je Eintrag. Implementiert in `gui_model.GuiController.collect_activity` / `cancel_activity` (ohne tkinter, Ereignis-Queue, Worker-Threads). `cancel_activity(kind, id)` ruft **genau** ein Abbruch-Verb auf (`cancel_goal`, `orchestrator.cancel`, `cancel_repair`, `tasks.cancel`) und startet, erstellt, setzt nichts fort und erteilt nichts (Strukturtest ueber die Namen in den Aktivitaetsfunktionen). Unbekannte Arten oder IDs werden ohne Aufruf abgelehnt. Abbrechen ist bei aktivem Notaus erlaubt: Stoppen ist immer zulaessig.

Die Meldung gibt die **tatsaechliche Antwort** der Schnittstelle wieder: *Abgebrochen* nur, wenn sie den Abbruch angenommen hat und der Eintrag beendet ist; *Abbruch angefordert (kooperativ)*, wenn er angenommen wurde, die Arbeit aber noch laeuft; *Nicht abgebrochen* mit der Begruendung der Schnittstelle (z. B. Agent ohne Abbruchunterstuetzung, bereits beendet); *Abbruch fehlgeschlagen* bei einem Fehler. Eine nicht lesbare Quelle erscheint als Hinweis statt zu fehlen; ausgeschaltete Quellen (Standard fuer Ziele, Agenten, Self-Repair) werden benannt. Grenzen: der Abbruch bleibt kooperativ; eine laufende `core.handle`-/LLM-Anfrage taucht hier nicht auf und ist nicht abbrechbar (dafuer gibt es den Notaus); die Liste ist eine Momentaufnahme (Aktualisieren) und zeigt hoechstens 50 Eintraege je Art.

## Gesamtbudget pro Sitzung (Teilziel 4) - umgesetzt

`permissions/budget.py` (`SessionBudget`, eigenes kleines Lock, injizierbare Uhr), gehalten von der `PermissionEngine` (einzige Kontrollstelle), gebaut in `permissions/factory.py` aus `[budget]` (`enabled = false` Standard; `max_tool_calls` 1..100000, `max_runtime_seconds` 0..86400; unbekannte Schluessel werden abgelehnt). Geprueft in `_evaluate` direkt nach dem Notaus (Notaus hat Vorrang), gebucht atomar erst bei der Genehmigung in `_authorize`; `execution_scope` prueft erneut nur die Laufzeit (ein bereits gebuchter letzter Aufruf darf laufen). Gezaehlt wird jeder genehmigte Aufruf (auch GREEN); verweigerte Aufrufe, abgelehnte Rueckfragen und `evaluate()` verbrauchen nichts; die Laufzeit beginnt mit der ersten gebuchten Aktion (monotonic).

Bei Ueberschreitung: weitere Aktionen werden verweigert (Regel `invariant:budget`, Meldung mit Verbrauch), ein Audit-Ereignis `budget_exhausted` einmalig; **nichts wird abgebrochen** (dafuer gibt es den Notaus). Kein Zuruecksetzen, keine Erhoehung, kein Einschalten im laufenden Prozess; weder Tools, Agenten noch Ziele erreichen das Budget (Strukturtest). CLI `/budget` zeigt nur den Verbrauch. Tests: `tests/test_session_budget.py` (39 Tests, Fake-Uhr, Nebenlaeufigkeit, Notaus-Vorrang, Strukturtest, Config-Grenzen). Linux-Lauf: volle Suite 3708 passed / 76 skipped; Windows-Nachweis ausstehend bis zum CI-Windows-Lauf. **Offen:** der kommentierte `[budget]`-Abschnitt in `config/jarvis.toml` fehlt noch (die Routine durfte `config/` nicht aendern); die Code-Standardwerte (aus) gelten, der Besitzer ergaenzt ihn. Grenzen: gezaehlt werden Tool-Aufrufe, keine LLM-Aufrufe/Kosten/Token; eine laufende Anfrage laeuft nach Ueberschreitung zu Ende; ein Neustart des Prozesses beginnt ein neues Budget.

## Weitere vorgeschlagene Teilziele (jeweils aus, bis ausdruecklich freigegeben; jeweils mit Abnahmetest)

1. ~~**Gemeinsamer Notaus.**~~ *(umgesetzt, siehe oben)* Urspruengliche Vorgabe: eine Funktion `core.halt_all(reason)`, die alle Subsysteme mit `halt`, offene Ziele (`cancel`) und offene Bestaetigungen abbricht; CLI `/halt` und
   ein Knopf in der GUI. *Abnahme:* Tests mit Fake-Subsystemen (jedes `halt` genau einmal, ein fehlschlagendes blockiert die anderen nicht, Ergebnis nennt jedes Subsystem,
   danach keine neue Aktion ohne `resume`), GUI-Test, Audit-Eintrag.
2. ~~**Sichtbarkeit laufender autonomer Arbeit.**~~ *(umgesetzt, siehe oben)* Urspruengliche Vorgabe: Statusbereich der GUI um aktive Ziele/Tasks mit Abbrechen-Knopf (nutzt nur `cancel`). *Abnahme:* Model- und View-Tests; der
   Knopf ruft ausschliesslich `cancel`/`halt`.
3. ~~**Autonomie-Invarianten als Tests.**~~ *(umgesetzt: `tests/test_autonomy_invariants.py`, 140 Tests; Linux-Lauf: volle Suite 3669 passed / 76 skipped; Windows-Nachweis ausstehend bis zum CI-Windows-Lauf)* Urspruengliche Vorgabe: Tests, die die harten Limits und Voreinstellungen festnageln (`enabled=false`, Obergrenzen, Replanning-Verbote) und per AST pruefen,
   dass `goals/` und `agents/` Tools nur ueber `ToolRegistry` aufrufen. *Abnahme:* Tests schlagen an, wenn jemand ein Limit lockert oder die Kontrollstelle umgeht.
4. ~~**Gesamtbudget pro Sitzung (optional).**~~ *(umgesetzt, siehe oben)* Urspruengliche Vorgabe: Obergrenze fuer Tool-Aufrufe/Laufzeit ueber alle Ziele; bei Ueberschreitung Stopp mit klarer Meldung. *Abnahme:* Tests mit Fake-Uhr.
5. **Nicht ohne neue, ausdrueckliche Entscheidung:** Hintergrund-/zeitgesteuerte Ziele, Selbststart, Fernsteuerung. Mindestvoraussetzungen waeren: `lockdown` oder
   `confirmation = "deny"`, Gesamtbudget (4), gemeinsamer Notaus (1) und Sichtbarkeit (2).
