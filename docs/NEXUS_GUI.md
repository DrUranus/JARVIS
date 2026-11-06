# JARVIS NEXUS (Control Center, Premium V2): Installation, Start, Bedienung, Tests

Stand: 2026-11-06. NEXUS ist die lokale Weboberflaeche des Control Centers (`src/jarvis/control_center/`). Sie ist **nur ein weiterer Client des UI-Vertrags** (`docs/UI_CONTRACT.md`):
sie fuehrt nichts selbst aus, kennt keine Berechtigungen und hat keinen eigenen Freigabeweg. Alle Befehle gehen ueber den Adapter an den Controller und die PermissionEngine,
der NOTAUS-Knopf loest den echten Notaus aus, Rueckfragen beantwortet allein die Engine (Ablehnen ist Standard).

## Installation (Windows)
```
py -3.13 -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"              # Kern; das Control Center braucht keine weitere Bibliothek (nur Standardbibliothek + Browser)
pip install -e ".[ui]"               # optional: pywebview fuer das Mini-Overlay (WebView2-Laufzeit, auf Windows 11 vorhanden)
pip install -e ".[voice]"            # optional: Mikrofon/Sprachausgabe (sounddevice, numpy)
```

## Start
Das Control Center startet **nur auf ausdruecklichen Befehl** und nur mit `control_center.enabled = true` (Standard aus, bewusst nicht in `config/jarvis.toml`), aktivem Assistenten
und aktiven Agenten:
```
set JARVIS_CONTROL_CENTER_ENABLED=true
set JARVIS_ASSISTANT_ENABLED=true
set JARVIS_AGENTS_ENABLED=true
jarvis-cc --open                      # gibt http://127.0.0.1:<Port>/?t=<Token> aus und oeffnet den Systembrowser
jarvis-cc --overlay --overlay-on-top  # optionales Mini-Overlay (140x140, verschiebbar, nie klickdurchlaessig)
```
Ohne diese Einstellungen bricht der Befehl mit Fehlercode 2 ab und es lauscht nichts. Der Server haengt nur an `127.0.0.1` (Token, Host- und Origin-Pruefung, strenge CSP).

## Oberflaeche
- **Orb-Modus (Start):** violett-blaue Kugel mit Tiefe (Nebel, Laengen-/Breitenkreise, Randlicht, Glanz), Ringen, Energieteilchen und Staub. Der Zustand steht als Chip und in der Kopfzeile.
- **Dashboard:** Agenten und Systemstatus links, Kugel, Gespraech und Ereignisse in der Mitte, Aufgaben, Details, Ergebnisse, Journal, Audit und Rueckfrage rechts.
  Der Systemstatus zeigt nur Werte aus echten Backend-Ereignissen (Verbindung, Zustand, Notaus, Mikrofon, Aufgaben, Agenten, Ergebnisse, Rueckfragen, Effekte, Ereignis-Nr.); ohne Meldung steht dort "unbekannt".
- **Wechsel:** manuell per Knopf; automatisch ins Dashboard nur bei belegbarer Komplexitaet (mindestens drei geplante Schritte oder zwei beteiligte Agenten), nie nach manueller Wahl.
- **Zustandsfarben:** bereit gruen, hoert zu blau, arbeitet violett, spricht tuerkis, wartet auf Rueckfrage gold, Fehler und NOTAUS rot (`web/core_states.json`). Gezeigt wird nur ein vom Backend gemeldeter Zustand.
- **Effekte:** voll, reduziert (ca. 20 Bilder/s) oder aus (flacher 2D-Fallback, einmal gezeichnet). `prefers-reduced-motion` und geringe Leistung schalten automatisch herunter.
- **Mini-Overlay:** `?view=overlay` bzw. `jarvis-cc --overlay`: Kern und NOTAUS, Klick auf den Kern oeffnet das Hauptfenster. Rueckfragen beantwortet nur das Hauptfenster (ohne Antwort: abgelehnt).
- **Sprache:** "Sprache starten/beenden" senden nur `start_voice`/`stop_voice`; Pegel und Welle kommen aus `voice_level`-Ereignissen. Das Mikrofon gehoert dem Backend.

## Automatisierte Tests
| Ebene | Datei | Was | Wo |
|---|---|---|---|
| Statik/Sicherheit | `tests/test_control_center_web.py`, `_server.py`, `_confirmation.py`, `_overlay.py` | keine externen Ressourcen, CSP, Token/Origin, Notaus ueber dem Dialog | Linux + Windows (`tests-linux`/`tests-windows`) |
| DOM-Ersatz (Node) | `tests/test_control_center_core.py`, `_dashboard.py`, `_voice.py`, `_status.py` | Zustaende, Farben, Dashboard, Systemstatus, 2D-Fallback | Linux + Windows, braucht `node` |
| Echter Browser (Chromium, headless) | `tests/test_control_center_e2e_browser.py` | Pixel/Farben je Zustand, Animation vs. statisch, Orb/Dashboard, Chat, Abbrechen, Freigabedialog (Ablehnen, Escape, Zeitablauf, Verbindungsverlust), Notaus (Fake und **echte Engine**), Overlay-Seite | Linux + Windows, Workflow `control-center-gui-e2e.yml` Job `browser-e2e` (Pflicht: kein Skip, mindestens 21 Tests) |
| Nativer Windows-Desktop | `tests/test_control_center_native_windows.py` | pywebview-Overlay als echtes Fenster: Groesse, Always-on-Top, Notaus per Mausklick auf dem Desktop, Screenshot | nur interaktiver Windows-Desktop: Workflow `control-center-gui-e2e.yml` Job `native-desktop` (nur manuell, `workflow_dispatch`); Nachweis erst mit vorliegendem Lauf |

Lokal (Browser-E2E): `pip install playwright` und `python -m playwright install chromium`, dann `python -m pytest -rfEs tests/test_control_center_e2e_browser.py`.
Optional `JARVIS_CHROMIUM_PATH=<chrome.exe>` fuer ein vorhandenes Chromium und `JARVIS_GUI_EVIDENCE=<Ordner>` fuer die Screenshots (Standard `reports/gui/e2e/`).

**Beweisgrenzen:** Headless-Browser-Tests sind **keine** native Fensterabnahme. Der native Test ist erst dann ein Nachweis, wenn der Workflow-Lauf mit seinen Screenshots vorliegt;
ohne Lauf steht die Abnahme (Issue #186) auf `pending`. Ein uebersprungener Test gilt nie als bestanden: die Workflows pruefen im JUnit-Bericht, dass nichts uebersprungen wurde.
