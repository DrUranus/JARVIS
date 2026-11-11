# OpenHands-Abhängigkeiten: statische Lizenz- und Schwachstellenprüfung

**Status: rein statische Prüfung, nichts installiert, nichts ausgeführt, nichts in JARVIS übernommen.** Freigabe des Besitzers: „weitere rein statische Lizenz- und Sicherheitsprüfung der OpenHands-Abhängigkeiten“. Ergänzt `docs/V2_OPENHANDS_SICHERHEITSBERICHT.md` und `docs/V2_ABSCHLUSS_VORBEREITUNG.md`. Stand 2026-11-11; `software-agent-sdk` Commit `06b358764bb7`, Datei `uv.lock`.

## 1. Methode und Grenzen
- Quelle: `uv.lock` (415 Einträge: 411 aus der Registry, 4 lokale Pakete `openhands-*`). Für jeden Registry-Eintrag wurde die PyPI-JSON-Seite der **genau gesperrten Version** gelesen (Felder `license_expression`, `license`, Klassifikatoren und das PyPI-Feld `vulnerabilities`). Nur Lesezugriffe, keine Installation.
- Die „Pflicht-Abhängigkeiten“ sind der Abschluss über die Felder `dependencies` der vier OpenHands-Pakete (ohne optionale Extras/Entwicklungsgruppen): **331 Einträge**. Plattformbedingte Abhängigkeiten (z. B. macOS-`pyobjc`) sind darin als Obergrenze enthalten.
- **Grenzen:** Lizenzangaben stammen aus Paketmetadaten und sind nicht rechtlich geprüft; die Schwachstellenangaben sind die von PyPI geführten, nicht unabhängig bestätigt; Schweregrade (CVSS) und tatsächliche Erreichbarkeit der Lücken wurden **nicht** geprüft; Binärräder/native Teile und Chromium im Image sind nicht Teil dieser Prüfung. `beartype`, `cryptography` und `google-cloud-storage` haben mehrere Lock-Einträge (Plattform/Python-Version); die Auswertung nennt je Name eine Version, Einzelfälle sind nachzuprüfen. Ein Treffer in der Lock-Datei bedeutet nicht, dass JARVIS diese Version einsetzen würde (bei `pip install` ohne Lock können neuere Versionen aufgelöst werden; ein aus `uv.lock` gebautes Image enthielte sie).

## 2. Lizenzen
**Ergebnis:** In den 331 Pflicht-Abhängigkeiten **kein AGPL- und kein reiner GPL-Eintrag**. Der Großteil ist MIT, Apache-2.0, BSD, ISC oder PSF.
| Fall | Pakete | Bewertung |
|---|---|---|
| **LGPL** | `func-timeout 4.3.5` (LGPLv2), benötigt von `openhands-tools` | `docs/INTEGRATIONS.md` schließt (A)GPL aus; LGPL ist dort nicht ausdrücklich genannt. Bei reiner privater Nutzung ohne Weitergabe unkritisch; vor einer Übernahme gesondert bewerten (Einschätzung). |
| **MPL-2.0** | `certifi`, `orjson` (MPL-2.0 AND Apache-2.0 OR MIT), `tqdm` (MIT + MPL-2.0) | schwaches Copyleft auf Dateiebene; für private Nutzung unkritisch; bei Weitergabe geänderter MPL-Dateien relevant |
| **Keine Metadaten, per Sdist geklärt** | `agent-client-protocol 0.12.1` → **Apache-2.0** (LICENSE-Datei gelesen); `cdp-use 1.4.4` → **MIT** (LICENSE gelesen, © 2025 Browser Use) | in Ordnung |
| **Ungeklärt** | `browser-use-sdk 2.0.15`, `lmnr-claude-code-proxy 0.1.23`: weder Lizenzfeld noch Lizenzdatei im Sdist | **Lizenz offen**, beim Upstream-Repository nachzuprüfen (nicht erfolgt) |
| nicht im Pflicht-Abschluss | `pyinstaller` (GPLv2 mit Ausnahme), `pyinstaller-hooks-contrib`, `docutils` (u. a. GPL), `pre-commit`, `pyright`, `google-cloud-aiplatform` | gehören zu Entwicklungs-/Extra-Gruppen; nicht Teil des Laufzeitabschlusses |
| Hauptkomponenten | `browser-use` MIT, `posthog` MIT, `lmnr` Apache-2.0, OpenHands/SDK MIT | siehe frühere Berichte |

Viele Pakete tragen die Lizenz nur im Freitextfeld (z. B. alle `pyobjc-*` „MIT“); das ist eine Metadatenschwäche, kein Befund.

## 3. Bekannte Schwachstellen (PyPI-Feld `vulnerabilities`, gesperrte Version)
Elf Pakete im Pflicht-Abschluss haben laut PyPI mindestens eine nicht zurückgezogene Meldung für die gesperrte Version (Anzahl Meldungen; „behoben in“ laut PyPI-Angabe, soweit vorhanden):
| Paket (gesperrt) | Meldungen | behoben in (PyPI) | Anmerkung |
|---|---|---|---|
| `aiohttp 3.14.3` | 8 | 3.14.4 | Netzwerk-Client/-Server, im Agent-Server relevant |
| `authlib 1.6.12` | 15 | 1.8.0 bis 1.9.1 | OAuth-Bibliothek |
| `pypdf 6.14.2` | 46 | 6.15.0 bis 6.18.1 | **kommt über `browser-use`**; unsere eigene Prüfdatei (`docs/integrations/pypdf.md`) nennt 7.0.1 ohne bekannte Meldung |
| `pyasn1 0.6.4` | 4 | – | |
| `pyjwt 2.14.0` | 4 | 2.15.0 | |
| `soupsieve 2.8.4` | 4 | – | HTML-Auswahl (Browser-/Extract-Pfad) |
| `oauthlib 3.3.1` | 3 | – | |
| `filelock 3.20.3` | 2 | – | |
| `fsspec 2025.9.0` | 2 | – | |
| `multidict 6.7.0` | 2 | – | |
| `opentelemetry-api 1.39.1` | 1 | – | |
Außerhalb des Pflicht-Abschlusses (Dev-/Extra-Gruppen) zusätzlich u. a. `cryptography` (Mehrfacheintrag; Version im Einzelfall prüfen), `virtualenv`, `setuptools`, `dnspython`.
**Folgerung:** Das Lock von OpenHands steht nicht auf den neuesten Patchständen; **ein Image oder eine Installation aus diesem Lock hätte mindestens elf Pakete mit offenen Meldungen**. Vor einem Prototyp: eigene Auflösung auf gepatchte Versionen prüfen oder die Lücken einzeln bewerten (Erreichbarkeit im Worker-Betrieb ohne Netz ist deutlich geringer, aber nicht null: lokale Eingaben, Dateien, HTML).

## 4. Telemetrie-/Netzbezug der Abhängigkeiten
Siehe `docs/V2_ABSCHLUSS_VORBEREITUNG.md` §4: `browser-use` (PostHog-Telemetrie standardmäßig an, Exception-Autocapture, Cloud-Sync-Standard an, Standard-Erweiterungen von `clients2.google.com`), `posthog`, `lmnr`. Zusätzlich im Pflicht-Abschluss: `litellm`, `mcp`, `fastmcp`, `opentelemetry-sdk`, `pywin32`. **Nicht gelesen:** Quellcode von `litellm` (kann Modell-Preislisten oder Weiteres laden; ungeprüft) und der übrigen Pakete.

## 5. Offene Punkte / nächster statischer Schritt (nur mit Freigabe)
1. Lizenz von `browser-use-sdk` und `lmnr-claude-code-proxy` beim Upstream klären.
2. Schweregrade/Erreichbarkeit der elf Pakete mit Meldungen bewerten (OSV-/GHSA-Texte lesen).
3. `litellm`-Quellarchiv statisch lesen (Netzaufrufe beim Import, Preisliste, Callbacks).
4. Prüfdateien nach `docs/INTEGRATIONS.md` nur für das, was tatsächlich übernommen würde (nicht für alle 331).
