# NEXUS Ultimate – Integrationsbasis und Abnahme

## Phase 0 · Basis vom 20. November 2026

| Bestandteil | Geprüfter Stand |
| --- | --- |
| JARVIS | main `7cc65b0e9fcda545f784d887e71c28a279669b04`, Merge von #228. Die Windows-Stabilisierung #260 wurde in claude/v2-integration gemergt und gehört zum offenen Stapel #258 |
| Premium-Frontend | Lokaler sauberer Checkout von NEXUS Ultimate 1.1.0, `a1b812649c3ebdbf37256b607e181350298c79db` |
| V2 #258 | Offen, `c1a97154a9d8`, Ziel main. Enthält Änderungen an Server, Launcher, Views und bestehender Weboberfläche. |
| V2.1 #259 | Offen, `3b9b100b0825`, Ziel claude/v2-integration. |
| Windows #261 | Offen, `3ff0761aad37`, Ziel claude/v2-integration. Sprach- und Abnahmearbeiten getrennt weiterführen. |
| Windows #186 | Offen. Interaktive Prüfung von Freigabedialogen, Not-Aus, Geräteverhalten und Wiederherstellung bleibt beim V1-Abnahmeverfahren. |

Der Integrationsbranch basiert auf main. Die Arbeiten in #251, #255 und #256 liefern zusätzliche Leseansichten, Zeitleiste und Freigabeverlauf auf einem anderen PR-Stapel. Vor einem späteren Zusammenführen die betroffenen Pfade und die dann gemergten Endpunkte erneut vergleichen. Weder der bestehende Windows-Abnahmebericht noch die Standardkonfiguration gehören zum Änderungssatz.

## Schnittstellen und Sicherheitsgrenzen

`jarvis-cc` erstellt über `control_center.launcher.build_server` den `ControlCenterServer` mit dem vorhandenen Assistentenadapter. Der HTTP-Handler prüft Host, Origin und Token vor dem Routing. `POST /command` prüft Größe und Schema und übergibt an `ControllerUiBackend.send`. Reset ist eine Anfrage an die Engine. Die Browserseite erhält keine Mikrofonberechtigung.

Auf main liefert `GET /events` beim ersten Aufruf einen Snapshot, bei Wiederaufnahme Ereignisse ab Sequenznummer. `ControllerUiBackend.snapshot()` markiert einen Client als angehängt. Nach dem letzten SSE-Client ruft der Server `detach()` auf. Das beendet offene Rückfragen und aktive Sprache. Ein zusätzlicher reiner Betrachter kann den Zeitpunkt dieser Trennung verschieben. Deshalb den bereits vorhandenen Datenstrom im selben V1-Fenster nutzen. Kein zweiter SSE-Teilnehmer für die Premium-Darstellung.

Die bestehende CSP erlaubt selbst gehostete Skripte und Stylesheets, verbietet Inline-Code und erbt für Frames und Schriften `default-src 'none'`. Der dokumentierte Control-Center-Vertrag fordert DOM-Ausgabe ohne `innerHTML`. Die eigenständige 1.1.0 verwendet HTML-Templates, lokale Schriftdateien und eine HTML-/CSS-Vorschau per Sandbox-Iframe. Aktive Editorinhalte und das Standalone-App-Bootstrap gehören bis zur Klärung der Vorschaugrenze nicht in den privilegierten Dokumentkontext. Das Vorschaukonzept braucht eine eigene Prüfung, bevor die Live-Workspace-Abnahme möglich ist.

## Fähigkeiten auf main

| Bereich | Tatsächliche Quelle und aktuelle Grenze |
| --- | --- |
| Overview | `/events` liefert hello, state, activity, emergency. Lesende Diagnose, Verlauf und Audit über `ReadViews`. |
| AI Core | StateEvent, EmergencyEvent, voice_level und chat über `interface/ui_events.py`. Sprache und Text sind Vertragsbefehle. |
| Live Workspace | `coding/workspace.py` begrenzt Projektpfade. Der HTTP-Vertrag enthält keinen Datei-Lese-/Schreib- oder Revisionsendpunkt. |
| Agent Center | activity, routing, task_update und result. `/view/agents` und `/view/trace` sind auf dieser Basis keine veröffentlichten Routen. |
| Creative Studio | Der lokale SVG-Generator gehört zum Premium-Frontend. Kein dedizierter Live-Kreativendpunkt im Server. |
| Coding Studio | Coding-Subsystem und Ergebnisereignisse vorhanden. Artefaktverweise sind Daten, keine zum Öffnen freigegebenen Dateipfade. |
| Business Center | `business/agent.py` und `research/` existieren. Über das Control Center laufen Aufträge über den normalen Text-/Aufgabenpfad. |
| Trading Center | `finance/agent.py`, `calc.py` und `paper.py`. Kein Broker, keine Orderintegration in diesem Vorhaben. |
| Automations | Keine Zeitplanverwaltung im geprüften UI-Befehlsschema. Lokale Demo-Regeln sind getrennt zu kennzeichnen. |
| Memory & Settings | Memory-Subsystem vorhanden. `/view/doctor` liefert Diagnose, jedoch keine HTTP-Verwaltung von Gedächtnis oder Konfiguration. |

## Test- und Freigabestrategie

Pro Stufe separat erfassen: Implementierung, automatisierte Tests, reale Windows-Hardware und Produktivfreigabe. Die reguläre V1-Oberfläche bleibt Standard. Geprüft werden Paketinhalt, authentifizierte Ressourcen, unveränderte CSP, Snapshot und getrennte Verbindung, Verhalten bei Not-Aus, Weiterfunktionieren der V1-Rückfragen und die Zahl der SSE-Clients. Für spätere Phasen zusätzlich veraltete Freigaben, Befehlsquittungen, Timeout, Konflikte bei Dateirevisionen, sichere Artefaktauflösung und Neustart prüfen.

Hardwareprüfungen gehören auf einen interaktiven Windows-Rechner mit benannter Version, Paketstand, E/A-Geräten und Grafikkarte. Installation aus einem frischen Paket, Mikrofon, Lautsprecher, WebView/Browser, Mehrfensterverhalten, Not-Aus und Rückkehr zur V1-Oberfläche einzeln protokollieren. Headless-CI und Linux-Läufe haben eine eigene Ergebnisspalte. Freigabe und Standardumschaltung folgen erst nach V1- und NEXUS-Abnahme.
