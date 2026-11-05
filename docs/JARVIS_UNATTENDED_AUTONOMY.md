# JARVIS: unbeaufsichtigte Entwicklung und Blocker-Behandlung (Entscheidungsvorlage)

Stand: 2026-11-05. **Vorschlag, noch keine Laufzeit- oder Sicherheitsregel geaendert.**

## Ziel
Der Besitzer moechte, dass Claude Code selbststaendig implementiert, zielgerichtet testet, Fehler korrigiert und nach erfolgreichem Merge mit dem naechsten bereits freigegebenen Backlog-Schritt fortsetzt. ChatGPT prueft bei verfuegbarem GitHub-Zugriff die Ergebnisse und benachrichtigt bei echten Blockern. Eine durchgehende Ausfuehrung durch ChatGPT ist ohne dauerhaften, handlungsfaehigen Runner und passende GitHub-Connector-Aktionen nicht garantiert.

## Entscheidungsregel fuer Routine/Controller (geplanter Code-PR)
1. **Kein unnoetiges needs_human:** Bei bereits im Repository dokumentierter Freigabe diese auswerten; keine erneute identische Frage. Fehlt ein nichtkritisches Detail, die im Vertrag definierte konservative Standardeinstellung verwenden und Entscheidung mit Begruendung protokollieren.
2. **Technische Fehler:** bis zu drei gezielte Fix-/Testzyklen; danach Fehler mit Logs als `blocked`/diagnostic melden, ohne Endlosschleife. Windows-CI zwingend bei Windows-Funktionen.
3. **Unvollstaendige Kriterien:** Nur nachweislich erfuellte Kriterien als `met` markieren. Fuer unerfuellte Kriterien einen konkreten Folgeschritt vorschlagen; keine Erfolgsmeldung und kein stilles Ueberspringen.
4. **Fortsetzung:** nur freigegebene Schritte, nach gruenen verpflichtenden Checks und den bestehenden Merge-Gates; keine Doppelstarts; atomarer Controller-Lock, Tages- und Kettenbudget sowie Not-Halt bleiben wirksam.
5. **Sicherheitsrelevante Ausnahmen:** PermissionEngine, X0-Vertrag, Not-Aus, Secrets, neue Abhaengigkeiten/Lizenzen ohne Freigabe, externe Aktionen mit hohen Auswirkungen und widerspruechliche Anforderungen duerfen nicht stillschweigend entschieden werden. Gezielte Eskalation mit einer einzigen konkreten Entscheidung statt pauschalem Block.
6. **Status:** automatischer Hinweis bei `blocked`, `partial`, `needs_human`, ausbleibendem Folgeauftrag nach Merge und fehlgeschlagenen Windows-Checks; jede Meldung enthaelt die Ursache und den naechsten Schritt.

## Naechste technische Umsetzung (separater PR)
- Bestehende `.github/automation/`-Controller- und Report-Tests lesen, dann minimalen Fix fuer bereits freigegebene Entscheidungen und konkrete Follow-up-Planung entwickeln.
- Kein direkter Schreibzugriff durch die Routine auf `main`; kein Umgehen der CI-/Merge-Gates.
- Tests fuer erneute identische Freigaben, fehlende Freigaben, fehlgeschlagene Windows-Checks, partielle Berichte, Doppelstart und Kettenbudget.
- Vor produktiver Aktivierung Windows-/Linux-CI und Test eines vollstaendigen Controller-Durchlaufs.

**Nicht autorisiert:** Sicherheitskontrollen ausschalten, `needs_human` blind zu `success` umschreiben, unbeschraenkte Schleifen, Sicherheitschecks entfernen oder ohne Nachweise mergen.

## Aktueller Lauf
Issue #164 ist bereits als laufender Auftrag gemeldet. Diesen Lauf nicht parallel neu starten oder durch diese Vorlage unterbrechen.
