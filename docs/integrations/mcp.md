# mcp (offizielles Model Context Protocol Python SDK)

Prüfbericht nach `docs/INTEGRATIONS.md`, Teil von V2-14 (MCP-Gateway, nur Dokumentationsphase). Geprüft wurden nur öffentliche Quellen (PyPI-Metadaten, LICENSE-Datei, Projektdokumentation, Sicherheitsmeldungen); **nichts wurde installiert oder heruntergeladen**, kein Fremdcode gelesen oder ausgeführt. Begleitdokument: `docs/MCP_SECURITY.md` (Bedrohungsmodell, Vergleich SDK gegen schlanken eigenen Client).

## Name und Zweck
`mcp` (Version 2.3.0), Projektseite und Quelle https://github.com/modelcontextprotocol/python-sdk, Paket https://pypi.org/project/mcp/. Offizielles Python-SDK des Model Context Protocol (Client und Server, Transporte stdio/HTTP, Autorisierung). JARVIS bräuchte davon **nur** den Client für `tools/list` und `tools/call` über stdio (siehe `docs/MCP_SECURITY.md`). Abhängiges Teilpaket: `mcp-types` 2.3.0.

## Lizenz (Wortlaut)
MIT
> "MIT License / Copyright (c) 2024 Anthropic, PBC / Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software" (Fundstelle: LICENSE im Repository, Zweig `main`, gelesen 2026-11-11, https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE; PyPI-Metadaten: `license_expression` "MIT").

Ergebnis: permissiv, kommerziell nutzbar.

## Version und Datum
**2.3.0**, PyPI-Upload am 2026-10-02 (Wheel `mcp-2.3.0-py3-none-any.whl` und Quellpaket). Nicht zurückgezogen (`yanked: false`). `mcp-types` 2.3.0 gleiches Datum. Die Hauptversion 2 bringt laut Veröffentlichungshinweisen mehrere Breaking Changes gegenüber 1.x; 1.x erhält weiter kritische Fixes ([Release v2.0.0](https://newreleases.io/project/github/modelcontextprotocol/python-sdk/release/v2.0.0), Sekundärquelle).

## Pflege
Aktiv: 73 Veröffentlichungen auf PyPI, jüngste 2026-10-02; Betreuer ist das Projekt `modelcontextprotocol` (Anthropic-Repository). Sicherheitsmeldungen werden mit Fixversionen veröffentlicht (siehe nächster Abschnitt). Laut v2.2.0-Notizen sind einige Erweiterungen (Tasks, DPoP, jwt-bearer) noch nicht umgesetzt. GitHub-Aktivität (Commits, offene Meldungen) wurde nicht geprüft.

## Python- und Windows-Kompatibilitaet
- `requires_python`: **>=3.10** (JARVIS verlangt >= 3.11, also kompatibel).
- Das Paket selbst ist reines Python (Wheel `py3-none-any`), also auf Windows installierbar. Eine Abhängigkeit `pywin32>=311` wird laut Metadaten bedingt gezogen (Windows).
- Native Teile stecken in Abhängigkeiten (siehe unten); für alle fünf nativen Pakete führt PyPI Windows-Wheels (cffi 16, cryptography 5, pydantic-core 18, pywin32 21, rpds-py 14 Windows-Wheels in der jeweils gelisteten Version).
- **Windows-Nachweis fehlt:** Es gibt keinen CI-Lauf von uns mit diesem Paket. Nach `docs/INTEGRATIONS.md` ist das ein Ausschlussgrund für `nehmen`, solange nicht belegt.

## Transitive Abhaengigkeiten
Aus den PyPI-Metadaten abgeleitet (Windows, ohne optionale Extras des SDK, angeforderte Extras der Abhängigkeiten berücksichtigt, Python-Marker nicht aufgelöst, also eine obere Schätzung): **25 Pakete**. JARVIS-Kern hat heute 0 harte Abhängigkeiten.

| Paket | Version | Lizenz | Hinweis |
|---|---|---|---|
| mcp | 2.3.0 | MIT | |
| mcp-types | 2.3.0 | MIT | |
| anyio | 4.16.0 | MIT | |
| pydantic | 2.14.3 | MIT | |
| **pydantic-core** | 2.50.4 | MIT | **native Teile (Rust)** |
| typing-extensions | 4.16.0 | PSF-2.0 | |
| typing-inspection | 0.4.5 | MIT | |
| annotated-types | 0.8.0 | MIT | |
| attrs | 26.1.0 | MIT | |
| jsonschema | 4.26.0 | MIT | |
| jsonschema-specifications | 2025.9.1 | MIT | |
| referencing | 0.37.0 | MIT | |
| **rpds-py** | 2026.9.1 | MIT | **native Teile (Rust)** |
| httpx2 | 2.16.0 | BSD-3-Clause | |
| idna | 3.20 | BSD-3-Clause | |
| starlette | 1.10.0 | BSD-3-Clause | Server-/HTTP-Teil, für einen stdio-Client ungenutzt |
| sse-starlette | 3.7.0 | BSD-3-Clause | Server-/HTTP-Teil, ungenutzt |
| python-multipart | 0.0.33 | Apache-2.0 | Server-/HTTP-Teil, ungenutzt |
| pyjwt | 2.15.1 | MIT | Autorisierung, ungenutzt |
| **cryptography** | 50.0.2 | Apache-2.0 OR BSD-3-Clause | **native Teile**, über `pyjwt[crypto]` |
| **cffi** | 2.1.1 | MIT-0 | **native Teile** |
| pycparser | 3.12 | BSD-3-Clause | |
| **pywin32** | 312 | PSF | **native Teile (Windows)** |
| opentelemetry-api | 1.45.2 | Apache-2.0 | |
| exceptiongroup | 1.3.1 | MIT | nur für Python < 3.11 |

Jede dieser Abhängigkeiten unterliegt denselben Regeln; bei einer Aufnahme wäre je Paket eine Hash-Pinnung (`pip-compile --generate-hashes`) und eine Prüfung der nativen Teile nötig.

## Sicherheitshinweise
- **Gemeldete Schwachstellen des SDK (2026), alle behoben in den genannten Versionen, 2.3.0 wird von der Registry mit 0 Meldungen geführt:**
  - CVE-2026-52869 (Autorisierungsumgehung, GHSA-jpw9-pfvf-9f58), behoben ab 1.27.2.
  - CVE-2026-52870 (fehlende Autorisierung, Tasks, GHSA-hvrp-rf83-w775), behoben ab 1.27.2.
  - CVE-2026-59950 (WebSocket-Transport ohne Host-/Origin-Prüfung, GHSA-vj7q-gjh5-988w), behoben ab 1.28.1.
  - Ein weiterer Eintrag (Debian: CVE-2026-116686, GHSA-rwrf-2pqf-9j8j, Fix 2.2.0) ist **nicht bestätigt**.
  - Einschätzung: Die Meldungen betreffen Autorisierungs-, Aufgaben- und WebSocket-Code, den ein stdio-Client nicht benutzt (**eigene Schlussfolgerung, Code nicht geprüft**). Sie zeigen aber, dass solcher Code mit installiert wird.
- **Native Teile:** fünf Pakete (siehe Tabelle) mit Windows-Wheels; Herkunft bekannt (PyPI), Inhalte nicht geprüft.
- **Install-/Import-Code:** die Wheels sind reines Python; Importcode und Abhängigkeiten wurden nicht gelesen.
- **Protokollrisiken** (unabhängig vom Paket): Tool Poisoning, Prompt Injection über Ergebnisse, Confused Deputy; Gegenmaßnahmen in `docs/MCP_SECURITY.md`.
- Benötigte Rechte: keine besonderen für einen stdio-Client; der **Server-Kindprozess** hat die Rechte des Benutzers, sofern er nicht isoliert wird (Sandbox-Frage, `docs/SANDBOX_DESIGN.md`).

## Datenabfluss
Als Client über stdio: keine eigene Netzwerkverbindung nötig; Telemetrie ist in der Dokumentation nicht beschrieben (**nicht geprüft**). `opentelemetry-api` ist enthalten, exportiert ohne SDK/Exporter nichts (Annahme, nicht geprüft). Speicherorte: keine eigenen. Daten, die einen Server erreichen, sind die Werkzeugargumente nach Freigabe; der Server selbst kann nach außen senden, wenn nicht isoliert (`docs/MCP_SECURITY.md`, M9).

## Pinning mit Hash
Nur zur Dokumentation, **kein Einbau**. Hashes aus den PyPI-Metadaten (nicht heruntergeladen, vor einer Aufnahme neu zu prüfen):
```
mcp==2.3.0 \
    --hash=sha256:dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377 \
    --hash=sha256:8b147a50441cf059dc88c684e0aeed3687f0aa0f39c6cde7b90330effd2b34d8
mcp-types==2.3.0 \
    --hash=sha256:968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d \
    --hash=sha256:d1e46549edb35ee19a94940fcee6d1addd7e589ab7ea92dda83f5d84781fc362
```
(Wheel und Quellpaket je Version.) Die Hashes der übrigen 23 Pakete fehlen bewusst; sie wären bei einer Aufnahme vollständig und plattformbezogen (Windows und Linux) zu erzeugen.

## Lizenzausschluss (AGPL/GPL)
Weder `mcp` noch eine der 25 aufgelisteten Abhängigkeiten ist laut Registry-Lizenzangabe AGPL oder GPL (gefunden: MIT, BSD-3-Clause, Apache-2.0, PSF-2.0, MIT-0, „Apache-2.0 OR BSD-3-Clause“). Lizenztexte der Abhängigkeiten wurden **nur aus den Registry-Feldern** gelesen, nicht aus den Lizenzdateien; vor einer Aufnahme ist das nachzuholen.

## Entscheidung
nicht nehmen

Begründung (Stand 2026-11-11; Neubewertung möglich):
1. Es gibt keinen Windows-CI-Nachweis für das Paket und seine fünf nativen Abhängigkeiten (Pflicht nach `docs/INTEGRATIONS.md`).
2. Für den benötigten Umfang (`tools/list`, `tools/call` über stdio) bringt das SDK rund 25 Pakete, fünf davon mit nativen Teilen, und viel ungenutzten Server-/HTTP-/Autorisierungscode in einen bisher abhängigkeitsfreien Kern; 2026 gab es mehrere Meldungen in genau diesen ungenutzten Teilen.
3. Die empfohlene Alternative ist ein schlanker eigener stdio-Client mit streng begrenzter Nachrichtenmenge (Vergleich und Neubewertungsbedingungen in `docs/MCP_SECURITY.md`, Abschnitt 6). Das SDK bleibt Referenz und optionaler Testgegner.
Diese Entscheidung ist ein Prüfergebnis, keine Freigabe und kein Verbot; jede Änderung braucht einen eigenen Besitzer-Schritt.

## Pruefung (Datum und Quelle)
2026-11-11. Quellen: PyPI-JSON `https://pypi.org/pypi/mcp/json` und der Abhängigkeiten (Version, Datum, `requires_python`, `requires_dist`, Lizenzfelder, Wheels, Hashes, gemeldete Schwachstellen); LICENSE im Repository; Spezifikation und Sicherheitsseiten auf modelcontextprotocol.io (Liste in `docs/MCP_SECURITY.md`, Abschnitt 10); Advisories: https://advisories.gitlab.com/pypi/mcp/CVE-2026-52869/ , https://advisories.gitlab.com/pypi/mcp/CVE-2026-59950/ ; Veröffentlichungshinweise v2.0.0 über newreleases.io (Sekundärquelle). Nicht geprüft: Quellcode, GitHub-Aktivität, tatsächliche Installation, CI-Läufe.
