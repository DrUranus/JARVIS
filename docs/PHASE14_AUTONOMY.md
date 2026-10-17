# Phase 14 "Maximum Autonomy": Bestand, Sicherheitsgrenzen und pruefbare Teilziele

Stand: nach Phase 11 (GUI). Dieses Dokument beschreibt, was von Phase 14 heute **wirklich** im Code ist, welche Grenzen die Autonomie schon begrenzen, und schlaegt
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
| Selbstaenderung gesperrt | Phase 15 ist ein deaktivierter Vorschlagsworkflow; `ExecutionGuard` ist immer gesperrt | keine Selbstmodifikation, keine Sandbox |

## Luecken (keine Behauptung von Sicherheit)

- Es gibt **keinen gemeinsamen Notaus**: jedes Subsystem wird einzeln angehalten.
- Die GUI zeigt keine laufenden Ziele/Agenten-Tasks mit Abbrechen-Knopf (nur schreibgeschuetzten Text).
- Ein einzelner `core.handle`-Aufruf laesst sich nicht unterbrechen.
- Kein Gesamtbudget (Aktionen/Zeit/Kosten) ueber mehrere Ziele hinweg.
- Windows-Prozesskontrolle ist Eindaemmung, keine Isolation (siehe README Phase 15).

## Vorgeschlagene Teilziele (jeweils aus, bis ausdruecklich freigegeben; jeweils mit Abnahmetest)

1. **Gemeinsamer Notaus.** Eine Funktion `core.halt_all(reason)`, die alle Subsysteme mit `halt`, offene Ziele (`cancel`) und offene Bestaetigungen abbricht; CLI `/halt` und
   ein Knopf in der GUI. *Abnahme:* Tests mit Fake-Subsystemen (jedes `halt` genau einmal, ein fehlschlagendes blockiert die anderen nicht, Ergebnis nennt jedes Subsystem,
   danach keine neue Aktion ohne `resume`), GUI-Test, Audit-Eintrag.
2. **Sichtbarkeit laufender autonomer Arbeit.** Statusbereich der GUI um aktive Ziele/Tasks mit Abbrechen-Knopf (nutzt nur `cancel`). *Abnahme:* Model- und View-Tests; der
   Knopf ruft ausschliesslich `cancel`/`halt`.
3. **Autonomie-Invarianten als Tests.** Tests, die die harten Limits und Voreinstellungen festnageln (`enabled=false`, Obergrenzen, Replanning-Verbote) und per AST pruefen,
   dass `goals/` und `agents/` Tools nur ueber `ToolRegistry` aufrufen. *Abnahme:* Tests schlagen an, wenn jemand ein Limit lockert oder die Kontrollstelle umgeht.
4. **Gesamtbudget pro Sitzung (optional).** Obergrenze fuer Tool-Aufrufe/Laufzeit ueber alle Ziele; bei Ueberschreitung Stopp mit klarer Meldung. *Abnahme:* Tests mit Fake-Uhr.
5. **Nicht ohne neue, ausdrueckliche Entscheidung:** Hintergrund-/zeitgesteuerte Ziele, Selbststart, Fernsteuerung. Mindestvoraussetzungen waeren: `lockdown` oder
   `confirmation = "deny"`, Gesamtbudget (4), gemeinsamer Notaus (1) und Sichtbarkeit (2).
