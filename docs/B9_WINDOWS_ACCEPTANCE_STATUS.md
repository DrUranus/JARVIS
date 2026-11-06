# B9 Windows-Smoke: Nachweise und offener GUI-Abnahmeschritt

Stand: 2026-11-06. Diese Datei dokumentiert **keine** erteilte Freigabe und **keinen** vollständigen B9-Abschluss.

## Automatisierte Nachweise

- PR #181: Windows- und Linux-CI grün, gemergt. Dokumentations-/Smoke-Vorarbeit.
- PR #184: Windows- und Linux-CI im letzten PR-Lauf grün, gemergt (Windows-SSE-Test korrigiert).
- Nachweis: https://github.com/DrUranus/JARVIS/pull/184
- Diese CI bestätigt den **headless** Control-Center-Server-Smoke, insbesondere Loopback/Host, Token/Origin, SSE/Befehl und Shutdown. Sie ist **kein** Nachweis für reale Windows-Fensterinteraktionen.

## Noch offen: echte Windows-GUI-Abnahme

Auf einem realen Windows-Desktop separat prüfen und Ergebnisse mit Datum, Build/Commit und reproduzierbaren Schritten protokollieren:

1. Orb ↔ Dashboard: manueller Wechsel und vorgesehene automatische Umschaltung.
2. Mini-Overlay: Fokus, Öffnen des Hauptfensters, optional Always-on-Top.
3. Freigaben: Sichtbarkeit, Ablehnung bei Schließen/Timeout/Verbindungsverlust; kein Bypass.
4. Not-Aus: in allen UI-Modi erreichbar und wirksam.
5. 3D-Rendering bzw. dokumentierter 2D-Fallback, reduzierte Animationen.

Bis dahin ist B9 **teilweise abgeschlossen**, nicht vollständig akzeptiert. Keine Kriterien stillschweigend entfernen, als bestanden markieren oder durch headless Tests ersetzen.

## Controller/Kette

- Issue #183 ist `partial` und Versuch 2/2 für `cc-windows-smoke`.
- Der Controller darf diesen Schritt wegen `max_attempts=2` und fehlender Freigabe nicht erneut automatisch versuchen.
- **Nicht** `AFTER_JOB=183` wiederholt auslösen und **keine** zweite parallele Routine starten.
- Vor einem neuen Kettenstart: offenen GUI-Nachweis erledigen **oder** einen separaten, explizit genehmigten Backlog-Schritt für die GUI-Abnahme festlegen. Der bestehende B9-Abnahmetext und alle Sicherheitsgrenzen bleiben unverändert.
- Für einen anderen nächsten Schritt sind dessen `approved=true`, Abhängigkeiten, Controller- und CI-Gates gesondert zu prüfen. Kein implizites Freigeben aller Backlog-Schritte.

Diese Dokumentation ist nur eine Nachweis- und Übergabekorrektur. Sie ändert weder `approved` noch `max_attempts`, PermissionEngine, X0, Not-Aus oder Controller-Startlogik.
