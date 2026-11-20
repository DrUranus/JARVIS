# NEXUS Ultimate 1.1.0 im lokalen Control Center

## Start und Rückkehr zu V1

Aus dem installierten Integrationsbranch im Repository-Stamm starten:

```console
jarvis-cc -c config/nexus.example.toml --nexus-preview --open
```

Unter Windows funktioniert derselbe Befehl im aktivierten Python-Venv. Die Einrichtungs- und Aktivierungsvoraussetzungen stehen in `docs/NEXUS_GUI.md`. Der Schalter wählt eine experimentelle Leseansicht. V1 bleibt bei einem normalen Start die Standardoberfläche. In der Titelleiste wechselt **V1-Oberfläche** im selben Fenster zurück. Beim nächsten Start den Schalter weglassen, um ganz zu V1 zurückzukehren. Das Paket führt keine Datenmigration aus.

Die NEXUS-Ansicht zeigt die Verbindung, den bestätigten Kernzustand und den Not-Aus. Projektdaten sind als lokale Beispiele gekennzeichnet. Für den bisherigen lokalen Editor, Projektnotizen, SVG-Export und die sandboxierte HTML-Vorschau enthält **Lokalen Workspace herunterladen** die eigenständigen Originaldateien und eine Startanleitung. Die ZIP enthält keinen Sitzungsschlüssel. Im authentifizierten Fenster werden die mit der bestehenden CSP erlaubten Ersatzschriften verwendet. Die Originalschriften sind im Paket und im lokalen Workspace enthalten.

## Architektur und geänderte Dateien

- `nexus_ultimate/` im Python-Paket enthält die 22 Originaldateien aus dem Premium-Commit `a1b812649c3ebdbf37256b607e181350298c79db`, einschließlich Schriften und Lizenzen. `pyproject.toml` nimmt die Ressourcen ins Wheel auf.
- `tools/render_nexus_views.mjs` erzeugt einmalig aus den originalen Views und lokalen Beispieldaten inerte Templates für alle elf Ansichten. Beim Start von JARVIS ist kein Node-Prozess erforderlich. Die Templates enthalten weder Frame noch Inline-Styles. Laufzeitereignisse werden nur über DOM-Eigenschaften angezeigt.
- `launcher.py`, `server.py` und `nexus_assets.py` liefern den Opt-in über den vorhandenen Loopback-Server. Die bisherige Host-/Origin-/Token-Prüfung und die Sicherheitsheader gelten auch für jeden Modul- und Ressourcenabruf. Der Server liefert nur explizit aufgelistete Premium-Ressourcen. Die Upload-, Datei- und Befehlsschnittstellen werden nicht erweitert.
- `web/app.js` meldet ausgewählte Statusereignisse des bestehenden SSE-Clients lokal an `nexus_preview/preview.js`. Ein Ansichtswechsel eröffnet keine zweite Verbindung. Nach einer Trennung werden der Status verworfen und auf derselben V1-Verbindung ein neuer Snapshot angefordert. Beide Ansichten teilen die bestehende V1-Befehls- und Freigabeleiste.
- `nexus_preview/host.css` und `surface.css` kapseln die Premium-Ansicht. Beim Öffnen eines echten V1-Freigabedialogs wird die Premium-Fläche für Eingaben gesperrt. Der ursprüngliche Not-Aus bleibt erreichbar.
- `tests/test_nexus_ultimate_preview.py` prüft Zugriff, Paketgrenzen und Lesemodus. `tests/test_nexus_ultimate_browser.py` verbindet Chromium mit dem realen Server und Controlleradapter. Testanfragen an den Freigabeprovider führen kein Werkzeug aus.

## Abnahmestand

| Bereich | Technisch implementiert | Automatisiert getestet | Reale Windows-Hardware | Produktivfreigabe |
| --- | --- | --- | --- | --- |
| Phase 0 | Baseline, Schnittstellen und konkurrierende Branches erfasst. Siehe PR #262. | GitHub-Refs und tatsächliche Codepfade abgeglichen. | Offen | Entfällt für Bestandsaufnahme |
| Phase 1 | Opt-in-Start, elf Ansichten, gemeinsamer Renderer, bestätigte Zustände, V1-Rückkehr und Download der lokalen Demo | Linux, Build aus dem Checkout, Installation eines frischen Wheels, Start mit echtem Launcher, authentifizierte Module, Chromium-Navigation, Verbindungsabbruch und frischer Snapshot | Offen | Offen |
| V1-Sicherheitsfunktionen in der Leseansicht | Vorhandener Not-Aus und vorhandene Freigabedialoge im selben Fenster | Echter Not-Aus, Ablehnen, einmaliges Bestätigen, Timeout, zwei Fenster, Schließen der letzten Verbindung und Erstfokus auf Ablehnen | Offen | Offen |
| Weitere Live-Funktionen | Eigene Premium-Befehlseingaben, Sprachsteuerung, Dateirevisionen und Backend-Werkzeuge stehen in dieser Leseansicht aus. | Bestehende V1-Tests sind separat zu bewerten. | Offen | Offen |

Die Sichtprüfung und Browserläufe erfolgen mit einem lokalen Test-Workspace und Mock-Modellanbieter. Ein vom Test im realen Adapter veröffentlichtes Listening-Ereignis prüft die Darstellung, nicht das Mikrofon. Beim Not-Aus-Klick prüft der Test den Zustand der realen Engine. Zwei bedienbare V1-Fenster teilen offene Rückfragen. Das erste Schließen lässt die zweite Oberfläche verfügbar, beim letzten Abbruch liefert der Bestätigungsprovider DENY.

## Offene Sicherheitsentscheidung für Phase 2

`ui_contract/fake.py::_refuse_in_emergency` verweigert bei aktivem Not-Aus jeden `confirm`-Befehl. `interface/ui_events.py::ControllerUiBackend._is_reset_answer` erlaubt die Antwort auf genau die von der Engine gestellte Reset-Rückfrage. `docs/UI_CONTRACT.md` dokumentiert diesen Unterschied und verlangt für die Klärung einen eigenen Vertrags-PR und eine Besitzerentscheidung. Zusätzlich enthält `tests/test_control_center_web.py` eine ausdrückliche Prüfung gegen einen Reset-Befehl in der bestehenden V1-Weboberfläche.

Vor dem Anschluss eines neuen Premium-Reset-Bedienelements muss der Vertragsreview festlegen, welches Verhalten beide Implementierungen garantieren. Es gibt keinen neuen Reset-Knopf und keine Frontend-Ausnahme. Die Diskrepanz ist unabhängig von #186. Phasen 3 bis 5 setzen die Abnahme des vollständigen Freigabe-/Not-Aus-Pfads voraus. Für Dateioperationen fehlt auf main zusätzlich ein bestätigter Lese-, Revisions- und Schreibvertrag. Die unabhängige Paketprüfung aus Phase 6 ist durchgeführt. Mikrofon, Lautsprecher, physische GPU, echte Windows-Fenster, Update/Rollback auf einem Zielsystem und Produktivfreigabe stehen aus.
