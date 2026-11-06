# Automatisierte GUI-Pruefungen (Windows)

Workflow: `.github/workflows/windows-control-center-gui.yml`, manuell oder bei relevanten PRs. Startet echten Chromium im **Headless-Modus** auf einem GitHub-Windows-Runner gegen den lokalen Control-Center-Server mit `FakeUiBackend`. Testet Orb/Dashboard-Wechsel, Sichtbarkeit des Notaus-Knopfes, Effekt-Auswahl und JavaScript-Fehler; speichert Screenshots und JUnit als Artefakte.

**Nachweisgrenzen:** Dies ist ein Browser-GUI-Test, **kein** interaktiver Windows-Desktop-Nachweis fuer natives pywebview-Mini-Overlay, echten Fokus/Always-on-Top, echte PermissionEngine-Freigaben, wirksamen Notaus oder GPU-/2D-Fallback. Die offene B9-Abnahme aus `docs/B9_WINDOWS_ACCEPTANCE_STATUS.md` bleibt offen, bis diese Punkte mit geeigneter Windows-Desktop-Automation oder manuellen Belegen bestaetigt sind. Keinen Test als bestanden ausgeben, wenn er skipped/fehlgeschlagen ist. CI ist fuer den neuen Workflow noch zu verifizieren.

Naechster Ausbau: Windows-Desktop-Testhost (interaktive Session, kontrollierte Testdaten) mit pywebview-Fenster und separatem Notaus-/Freigabe-End-to-End-Test. Vorher keine Aenderung von `approved`, `max_attempts`, X0 oder PermissionEngine.
