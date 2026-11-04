# Control Center: Oberflaechen-Technik (Auftrag ui-tech-evaluation, Strang B, Schritt B0)

Reine Pruefung nach `docs/INTEGRATIONS.md`. **Kein Code, keine Installation, keine Bibliotheksfreigabe.** Alle Angaben stammen aus offiziellen Quellen (PyPI-JSON, npm-Registry, LICENSE-Dateien im Repository, Projekt- und Herstellerdokumentation, MDN/Python-Dokumentation) und tragen Quelle und Abrufdatum (2026-11-04). Nicht pruefbare Punkte stehen ausdruecklich als **unbekannt/offen**. Die Entscheidungen unten betreffen die Aufnahme einer *Bibliothek*; die Empfehlung (Abschnitt "Empfehlung") ist davon getrennt.

**Pruefgrenzen dieser Sitzung (ehrlich):** GitHub-Seiten und die GitHub-API fuer die Fremd-Repositories waren in der Sitzung gesperrt (HTTP 403). Daher keine GitHub-Release-Seiten, keine GitHub-Advisory-Datenbank. Ersatz: `raw.githubusercontent.com` (LICENSE, SECURITY.md, pyproject.toml), PyPI-Metadaten (`vulnerabilities`-Feld, Release-Daten, Hashes), npm-Registry. Es wurde **nichts gemessen oder ausgefuehrt** (keine Performance- oder GUI-Messung, keine Installation); Performance-Aussagen sind Dokumentationsaussagen oder als "nicht gemessen" markiert. Alles gilt als **Windows-Nachweis ausstehend**.

## Name und Zweck
Pruefgegenstand: Technik fuer das Control Center (Strang B, Vertrag `docs/UI_CONTRACT.md`, Transport-Vorschlag: Loopback, Token, SSE/POST).
Kandidaten:
1. **Standardbibliothek-Server** (`http.server`/`ThreadingHTTPServer`, Server-Sent Events) + Browser-Oberflaeche (HTML/CSS/JS, keine Abhaengigkeit).
2. **pywebview 6.2.1** (https://pywebview.flowrl.com/, https://github.com/r0x0r/pywebview) mit WebView2 fuer ein natives Fenster.
3. **Zeichnen im Webview:** Canvas 2D (Browser-Standard), **Three.js** (https://threejs.org/, npm `three`), **PixiJS** (npm `pixi.js`).
4. **Alternativen:** **PySide6** (Qt for Python), **Dear PyGui**, **Flet**.
5. **Laufzeit:** Microsoft Edge WebView2 Runtime (Windows 10/11).
Bedarf von JARVIS: Dashboard, Rueckfragen/Bestaetigung, Notaus, Sprachvisualisierung, "Premium V2" (3D-Effekt, Mini-Overlay), alles strikt lokal und standardmaessig aus.

## Lizenz (Wortlaut)
Entscheidend sind die LICENSE-Dateien der gepruefen Version. Wortlaut (Auszuege, woertlich):

- **Standardbibliothek** (`http.server`): Python-Lizenz PSF-2.0 (Teil der Python-Distribution; kein eigenes Paket, keine Pflicht zur Aufnahme in `pyproject.toml`).
- **pywebview 6.2.1**, SPDX BSD-3-Clause:
  > "BSD 3-Clause License ... Copyright (c) 2014-2017, Roman Sirokov ... Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission."
  (Fundstelle: https://raw.githubusercontent.com/r0x0r/pywebview/6.2.1/LICENSE; PyPI-Klassifikator "License :: OSI Approved :: BSD License")
- **Three.js 0.187.0**, MIT: > "The MIT License / Copyright (c) 2010-2026 three.js authors / Permission is hereby granted, free of charge, to any person obtaining a copy of this software ..." (Fundstelle: https://raw.githubusercontent.com/mrdoob/three.js/dev/LICENSE; npm-Feld `license: MIT`)
- **PixiJS 8.22.0**, MIT: > "The MIT License / Copyright (c) 2013-2023 Mathew Groves, Chad Engler / Permission is hereby granted, free of charge ..." (Fundstelle: https://raw.githubusercontent.com/pixijs/pixijs/dev/LICENSE; npm `license: MIT`). Lizenzen der 10 direkten npm-Abhaengigkeiten **nicht geprueft (unbekannt)**.
- **Dear PyGui 2.3.1**, MIT: > "MIT License / Copyright (c) 2026 Dear PyGui, LLC / Permission is hereby granted, free of charge ..." (Fundstelle: https://raw.githubusercontent.com/hoffstadt/DearPyGui/v2.3.1/LICENSE; PyPI "MIT")
- **Flet 1.0.5**, Apache-2.0: > "Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/" (Fundstelle: https://raw.githubusercontent.com/flet-dev/flet/v1.0.5/LICENSE; PyPI `Apache-2.0`). **Transitiv: `certifi` 2026.10.23 ist MPL-2.0** (PyPI-Metadaten; ueber `httpx`), also schwaches Copyleft: nur mit ausdruecklicher Besitzerfreigabe zulaessig.
- **PySide6 6.12.0** (und `PySide6_Essentials`, `PySide6_Addons`, `shiboken6`): PyPI-SPDX-Ausdruck **`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`** (Fundstelle: https://pypi.org/pypi/PySide6/json). Qt-Lizenzseite (https://www.qt.io/qt-licensing): "Use Qt under the LGPL or GPL license ... allowing others to modify, distribute, and use your code, as per open source obligations" und "Your software must be open to copy, modify, and distribute". Der volle LGPL-Text wurde hier **nicht** im Wortlaut zitiert. Nach `docs/INTEGRATIONS.md` ist LGPL nur bei dynamischer Nutzung und nur mit ausdruecklicher Besitzerfreigabe zulaessig.
- **Pywebview-Kette (Windows):** pythonnet 3.2.1 MIT (LICENSE: "MIT License / Copyright (c) 2006-2021 the contributors of the Python.NET project"), clr_loader 0.3.1 (LICENSE-Datei im Repository abrufbar, 1079 Byte, MIT-Text; PyPI-Lizenzfeld leer: SPDX-Angabe dort **unbekannt**), cffi 2.1.1 MIT-0, pycparser 3.12 BSD-3-Clause, bottle 0.13.4 MIT, proxy_tools 0.1.0 MIT (PyPI), typing_extensions 4.16.0 PSF-2.0.
- **WebView2:** Das *SDK* (NuGet `Microsoft.Web.WebView2` 1.0.4314.35, Stand 2026-10-23) steht unter einer BSD-artigen Lizenz ("Redistribution and use in source and binary forms, with or without modification, are permitted ..."; https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4314.35/License). pywebview nutzt die SDK-DLLs mit. **Die Lizenzbedingungen der WebView2-*Runtime* selbst (Microsoft-Software, kein Open Source) wurden im Wortlaut nicht geprueft: unbekannt/offen.** Die Runtime wird nicht von JARVIS verteilt, sondern ist Teil von Windows 11 bzw. auf Windows 10 meist vorhanden (siehe Kompatibilitaet).

## Version und Datum
| Kandidat | gepruefte Version | Veroeffentlichung | Quelle |
|---|---|---|---|
| Standardbibliothek | je Python-Version (>= 3.11) | n/a | https://docs.python.org/3/library/http.server.html |
| pywebview | 6.2.1 | 2026-04-15 | PyPI |
| pythonnet | 3.2.1 | 2026-10-08 | PyPI |
| clr_loader | 0.3.1 | 2026-04-18 | PyPI |
| cffi / pycparser | 2.1.1 / 3.12 | 2026-08-03 / 2026-10-22 | PyPI |
| bottle | 0.13.4 | 2025-06-15 | PyPI |
| proxy_tools | 0.1.0 | 2014-05-05 | PyPI |
| typing_extensions | 4.16.0 | 2026-07-02 | PyPI |
| Three.js | 0.187.0 | 2026-10-30 | npm-Registry |
| PixiJS | 8.22.0 | 2026-10-01 | npm-Registry |
| Dear PyGui | 2.3.1 | 2026-05-01 | PyPI |
| Flet | 1.0.5 | 2026-10-21 (Folgeveroeffentlichungen bis 2026-11-03 in der Release-Historie) | PyPI |
| PySide6 | 6.12.0 | 2026-10-08 (weitere Veroeffentlichung 2026-10-26) | PyPI |
| WebView2-SDK (NuGet) | 1.0.4314.35 | zuletzt aktualisiert 2026-10-23 | nuget.org |

## Pflege
Belegt nur durch Veroeffentlichungshistorie (PyPI/npm) und die vorhandenen SECURITY.md; GitHub-Aktivitaet (Issues, Commits, Reaktion auf Meldungen) war **nicht abrufbar: unbekannt**.
- **pywebview:** 73 Veroeffentlichungstage auf PyPI, letzte 2026-04-15 (zuvor 2026-04-13, 2025-10-21). SECURITY.md: "Only the latest released version of pywebview is supported." Meldung per E-Mail an den Betreuer (Einzelperson). Letzte Veroeffentlichung vor etwa 6,5 Monaten.
- **proxy_tools** (Pflicht-Abhaengigkeit von pywebview): einzige Veroeffentlichung 2014-05-05, nur Quellpaket, **seit ueber 12 Jahren unveraendert** = aufgegeben (Regel "Pflege": nur mit schriftlicher Begruendung). bottle: zuletzt 2025-06-15.
- **Three.js:** sehr aktiv (0.187.0 am 2026-10-30; npm zuletzt geaendert 2026-10-30). Keine Semver-1.0: jede Version kann brechende Aenderungen bringen (Pinning Pflicht).
- **PixiJS:** aktiv (8.22.0 am 2026-10-01).
- **Dear PyGui:** 43 Veroeffentlichungstage, letzte 2026-05-01.
- **Flet:** sehr aktiv (91 Veroeffentlichungstage, letzte 2026-11-03), junge 1.0-Reihe.
- **PySide6:** aktiv, Herstellerprojekt (Qt Company), Releases 2026-10-08 und 2026-10-26.
- **WebView2 Runtime (Evergreen):** wird von Microsoft automatisch aktualisiert (Distribution-Dokumentation).

## Python- und Windows-Kompatibilitaet
Projektziel: Python >= 3.11, Windows 10/11.
- **Standardbibliothek:** laeuft ueberall; reine Python-Loesung. Browser: jeder aktuelle Chromium/Edge; Windows 10/11 hat Edge.
- **pywebview 6.2.1:** `requires_python >=3.8`, reines Wheel (`py3-none-any`). Windows: Abhaengigkeit `pythonnet` (>=3.11, <3.16, reines Wheel) -> `clr_loader` -> `cffi` (Windows-Wheels `win_amd64` fuer cp310 bis cp315 vorhanden) -> `pycparser`. Offizielle Doku (https://pywebview.flowrl.com/guide/web_engine.html): Renderer `edgechromium` = "Chromium > .NET Framework 4.6.2 and Edge Runtime installed" (Evergreen); `mshtml` = veraltet (IE11). Die Installationsseite nennt an anderer Stelle ".NET 4.0": **Widerspruch in der Doku**, massgeblich ist die strengere Angabe 4.6.2 (Windows 10/11 bringen .NET Framework 4.8.x mit - diese Aussage stammt nicht aus einer geprueften Quelle: offen).
- **WebView2 Runtime:** laut Microsoft (https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/evergreen-vs-fixed-version) ist die Evergreen-Runtime "preinstalled onto all Windows 11 devices"; fuer Windows 10 gilt "The vast majority of Windows 10 devices have the WebView2 Runtime installed already" - Microsoft empfiehlt dennoch, sie zur Sicherheit mitzuverteilen. Es ist also nicht garantiert; Erkennung und Hinweis noetig.
- **Three.js / Canvas 2D / PixiJS:** reine Browserbibliotheken (ES-Module), brauchen Python nicht.
- **Dear PyGui 2.3.1:** `requires_python >=3.8`, native Wheels `win_amd64` fuer cp38 bis cp314 (1,9 MB) und Linux (manylinux1). Zeichnet per eigener GPU-Schicht (Dear ImGui); keine Webtechnik.
- **Flet 1.0.5:** `>=3.10`, Flutter-basierter Desktop-Client im Paket `flet-desktop` (Apache-2.0); Windows-Wheel-Liste und Binaerherkunft des Clients **nicht geprueft: unbekannt**.
- **PySide6 6.12.0:** `>=3.10, <3.16`; Windows-Wheel `cp310-abi3-win_amd64` (Meta-Paket 0,6 MB, aber `PySide6_Essentials` 82,2 MB + `PySide6_Addons` 40,5 MB + `PySide6_WebEngine` + `PySide6_Pdf` per Abhaengigkeit) = mindestens ca. 120 MB Download.
- **Linux:** nur Zusatzpruefung; pywebview braucht dort GTK oder Qt (Extras), nicht Teil der Zielplattform. **Alle Windows-Aussagen oben sind Dokumentation, kein Lauf: Windows-Nachweis ausstehend.**

## Transitive Abhaengigkeiten
- **Standardbibliothek-Server:** keine.
- **pywebview 6.2.1 (Windows):** `pythonnet` (MIT) -> `clr_loader` (Lizenzfeld leer, Repository-LICENSE MIT-Text) -> `cffi` (MIT-0) -> `pycparser` (BSD-3-Clause); `proxy_tools` (MIT, 2014), `bottle` (MIT), `typing_extensions` (PSF-2.0). Optionale Extras (`qt`, `gtk`, `pyside6`, `ssl` = `cryptography` u. a.) sind nicht Teil der Standardinstallation. Auf Linux/macOS kommen weitere hinzu (nicht Zielplattform). Insgesamt 7 zusaetzliche Pakete, davon 2 mit nativem Code (cffi; WebView2-DLLs im pywebview-Paket) bzw. .NET-Bruecke.
- **Three.js:** `dependencies` = keine (npm-Metadaten); wird als einzelne Datei lokal eingebunden (kein CDN).
- **PixiJS:** 10 direkte npm-Abhaengigkeiten (earcut, tiny-lru, gifuct-js, ismobilejs, @pixi/colord, @types/earcut, @webgpu/types, eventemitter3, @xmldom/xmldom, parse-svg-path); Lizenzen und Tiefe **nicht geprueft: unbekannt**.
- **Dear PyGui:** keine (`requires_dist` leer).
- **Flet 1.0.5:** `oauthlib` (BSD-3), `httpx` (BSD-3) -> `httpcore` (BSD-3), `anyio` (MIT), `certifi` (**MPL-2.0**), `idna` (BSD-3), `h11` (MIT); `repath` (MIT), `msgpack` (Apache-2.0); fuer den Desktop-Client `flet-desktop`, `rich`. Baum nicht vollstaendig aufgeloest.
- **PySide6 6.12.0:** `PySide6_Essentials`, `PySide6_Addons`, `PySide6_WebEngine`, `PySide6_Pdf`, `shiboken6` - alle LGPL-3.0/GPL-Ausdruck.

## Sicherheitshinweise
- PyPI-Feld `vulnerabilities` war fuer pywebview, pythonnet, clr_loader, cffi, pycparser, bottle, proxy_tools, typing_extensions, Dear PyGui, PySide6, shiboken6 und Flet in den geprueften Versionen **leer** (Abruf 2026-11-04). Das ist kein Beweis der Fehlerfreiheit; die GitHub-Advisory-Datenbank war nicht erreichbar (403): **unbekannt**.
- **http.server:** Python-Dokumentation: "http.server is not recommended for production. It only implements basic security checks." Fuer JARVIS gelten daher zwingend die Schutzmassnahmen aus `docs/UI_CONTRACT.md` (nur `127.0.0.1`, Zufalls-Token, Host-/Origin-Pruefung, `MAX_COMMAND_BYTES` vor dem Parsen, kein Verzeichnislisting, nur eigene Dateien ausliefern). Ein Zugriff durch andere lokale Benutzer/Prozesse und DNS-Rebinding sind die Hauptrisiken; ohne Token + Host-Pruefung unzulaessig.
- **SSE:** MDN: ohne HTTP/2 hoechstens 6 offene Verbindungen je Browser und Host; daher genau ein Ereignisstrom je Fenster und Befehle per POST.
- **pywebview:** Die Doku (https://pywebview.flowrl.com/guide/security.html) empfiehlt SSL fuer den lokalen Server (braucht `cryptography`, nicht Standard) und nennt einen sitzungsweiten CSRF-Token (`webview.token`). Die JS-Python-Bruecke (`js_api`) ist eine Angriffsflaeche: fuer JARVIS darf **keine** Bruecke exponiert werden, nur der Vertrag (SSE/POST) mit Token. `debug` (WebView2-DevTools) muss aus bleiben. SECURITY.md: Einzelbetreuer, nur neueste Version unterstuetzt. Native Teile: pythonnet/.NET-Bruecke und WebView2-DLLs; Code bei Import: .NET-Laden (nicht im Detail geprueft).
- **WebView2:** Microsoft-Doku: Das Flag `disable-gpu` "Disables GPU hardware acceleration. If a software renderer isn't in place, the GPU process doesn't launch."; Browser-Argumente per `AdditionalBrowserArguments`. Die Runtime wird per Evergreen von Microsoft gepatcht (positiv).
- **Flet/PySide6/Dear PyGui:** native Binaerteile grosser Pakete (Flutter-Client, Qt, ImGui-Backend); Herkunft nur ueber PyPI-Hashes belegt, nicht geprueft.
- **Notaus-Sicherheit:** Kein Kandidat darf den Notaus ersetzen; er muss unabhaengig von UI-Prozess und Browser wirken (siehe Notaus-Abschnitt).

## Datenabfluss
- **Standardbibliothek-Server:** kein Abfluss; bindet nur an Loopback. Browser: eigenes Browserprofil (Edge) kann Telemetrie/Sync haben (Verantwortung des Browsers, nicht von JARVIS): bei Nutzung des Systembrowsers **offen** (Datenschutz-Seite der Edge-Dokumentation war nicht abrufbar, HTTP 404 bei `webview2/concepts/privacy`).
- **pywebview:** eigene Telemetrie in der Doku **nicht gefunden (unbekannt)**; `private_mode=True` ist laut API-Doku der Standard von `webview.start` (kein dauerhaftes Profil), `storage_path` gibt den Ablageort an. Die Runtime von Microsoft kann Diagnosedaten senden: Umfang aus der geprueften Doku nicht belegt: **offen**.
- **Three.js / Canvas 2D:** kein Netzwerk, wenn lokal ausgeliefert (kein CDN, keine Fonts/Texturen von aussen: Pflicht).
- **Flet:** `httpx`/`oauthlib` deuten auf Netzzugriff; Telemetrie/Update-Verhalten **nicht geprueft: unbekannt** -> spricht gegen "nehmen".
- **Dear PyGui, PySide6:** Telemetrie in der geprueften Metadatenlage nicht belegt; nicht untersucht (unbekannt).
- Allgemein fuer JARVIS: Ereignisse sind laut Vertrag bereits geschwaerzt; die Oberflaeche darf keine externen Ressourcen laden (Content-Security-Policy `default-src 'self'` verlangen).

## Pinning mit Hash
Es wird **nichts** gepinnt oder aufgenommen (keine Freigabe). Zur Vorbereitung, falls der Besitzer pywebview oder Dear PyGui spaeter freigibt: SHA-256 laut PyPI-JSON vom 2026-11-04 (Windows- und Linux-Artefakte fuer CPython 3.11-3.13; die Hashes stammen aus der Pruefung):

```
# pywebview-6.2.1-py3-none-any.whl
pywebview==6.2.1 --hash=sha256:9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46
# pythonnet-3.2.1-cp311.cp312.cp313.cp314.cp315-none-any.whl
pythonnet==3.2.1 --hash=sha256:dd5668b74b0c903d9a24e1ba86f728fc490f8e919d56b3c24bf06739b9ee2b7f
# clr_loader-0.3.1-py3-none-any.whl
clr_loader==0.3.1 --hash=sha256:cbad189de20d202a7d621956b0fc38049e13c9bf7ca2923441eff725cd121aa1
# cffi-2.1.1-cp311-cp311-manylinux1_i686.manylinux2014_i686.manylinux_2_17_i686.manylinux_2_5_i686.whl
cffi==2.1.1 --hash=sha256:154852545011f779917b11c78db2358d095da62a9a172b78ad0a583ee5adc0d0
# cffi-2.1.1-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
cffi==2.1.1 --hash=sha256:3311ed60d36f83378794e1009ac6258bafbf81f7888b4caa7b35a521e3f95813
# cffi-2.1.1-cp311-cp311-manylinux2014_ppc64le.manylinux_2_17_ppc64le.whl
cffi==2.1.1 --hash=sha256:6e192623c49c94421616a5778fba35cf0d5a8d000650c1967ef4448ee5cdd990
# cffi-2.1.1-cp311-cp311-manylinux2014_s390x.manylinux_2_17_s390x.whl
cffi==2.1.1 --hash=sha256:a6e721d4b0e45d5b65e87534470e67b18dcd092c83f68fba09f152b9cbc061af
# cffi-2.1.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
cffi==2.1.1 --hash=sha256:34e261f78cb6ceaaa36f42f2613f4380d94d9c759a9c73c769ee6e0247364632
# cffi-2.1.1-cp311-cp311-win_amd64.whl
cffi==2.1.1 --hash=sha256:42f6930c31dc7f50732c9ae793c2786c7b6b044195967bbdde40bb9be81c4cc0
# cffi-2.1.1-cp312-cp312-manylinux1_i686.manylinux2014_i686.manylinux_2_17_i686.manylinux_2_5_i686.whl
cffi==2.1.1 --hash=sha256:811bd1e21d32de12efca32393a0ab3f5133b54fce9bd44b8bd77ab07da14bf6a
# cffi-2.1.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
cffi==2.1.1 --hash=sha256:68e62fe11f30d5ca8289242866f0a5291402d8529ca2178ab8afc5c9694ae890
# cffi-2.1.1-cp312-cp312-manylinux2014_ppc64le.manylinux_2_17_ppc64le.whl
cffi==2.1.1 --hash=sha256:4a7c934f7360e8cd64fe9efadcbd10c7c6364f531e432b9a4bf5ccbc9e0e8b50
# cffi-2.1.1-cp312-cp312-manylinux2014_s390x.manylinux_2_17_s390x.whl
cffi==2.1.1 --hash=sha256:3143d81e29e1e20a9ce10901ec369012947876596f75a222235965f2b7ae832e
# cffi-2.1.1-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
cffi==2.1.1 --hash=sha256:c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf
# cffi-2.1.1-cp312-cp312-win_amd64.whl
cffi==2.1.1 --hash=sha256:f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a
# cffi-2.1.1-cp313-cp313-manylinux1_i686.manylinux2014_i686.manylinux_2_17_i686.manylinux_2_5_i686.whl
cffi==2.1.1 --hash=sha256:6a8dddef476fab96d066d578fc88526767b836ab5ab21754e1d5bf3879c31c7c
# cffi-2.1.1-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
cffi==2.1.1 --hash=sha256:f16c709686a78c727bbbf059f92b0bf41c6fc60deec706d2dc19f529175a6125
# cffi-2.1.1-cp313-cp313-manylinux2014_ppc64le.manylinux_2_17_ppc64le.whl
cffi==2.1.1 --hash=sha256:fcd22650c908d7b7da162bbfaab594a1227a15d1643a98c68b122ac642fa2264
# cffi-2.1.1-cp313-cp313-manylinux2014_s390x.manylinux_2_17_s390x.whl
cffi==2.1.1 --hash=sha256:aa9511c62d14da7aacc9b4bf51f3f697a621e83b2d6919008243c3aad168eea3
# cffi-2.1.1-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
cffi==2.1.1 --hash=sha256:a931079504ecc49efed7744c476a5c343a92fabf66dec2db95edb1b2fdc770e2
# cffi-2.1.1-cp313-cp313-win_amd64.whl
cffi==2.1.1 --hash=sha256:1aa5645c30469b09530c4ebca77ebf8f17618293c58f8549cb1a543a50236e7d
# pycparser-3.12-py3-none-any.whl
pycparser==3.12 --hash=sha256:a076f3f489b39b43ed13563a1dafe42447445bec2e294154ec5c57fcdda4c85e
# bottle-0.13.4-py2.py3-none-any.whl
bottle==0.13.4 --hash=sha256:045684fbd2764eac9cdeb824861d1551d113e8b683d8d26e296898d3dd99a12e
# typing_extensions-4.16.0-py3-none-any.whl
typing-extensions==4.16.0 --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8
# dearpygui-2.3.1-cp311-cp311-manylinux1_x86_64.whl
dearpygui==2.3.1 --hash=sha256:686423b4f8a30aaf57f1044ec4e3b087beb9cc9b25be812cf92f4e7feff44fd6
# dearpygui-2.3.1-cp311-cp311-manylinux2014_aarch64.whl
dearpygui==2.3.1 --hash=sha256:0259a2db7b6c82459ac1402b0d42388a7cd180cd97d7dcb31a5210725c3171d3
# dearpygui-2.3.1-cp311-cp311-win_amd64.whl
dearpygui==2.3.1 --hash=sha256:76ee38696a8f1f3805751b1588c98d9bb6567b033b91cb0f58111fb9fe907b5b
# dearpygui-2.3.1-cp312-cp312-manylinux1_x86_64.whl
dearpygui==2.3.1 --hash=sha256:364b5b6a0953999fec764d529d9bb0b2cc6ab6ed06188e0ded28237c1475ca98
# dearpygui-2.3.1-cp312-cp312-manylinux2014_aarch64.whl
dearpygui==2.3.1 --hash=sha256:199dffebda245c9f59aa7c10c3b7f62963237c5f744150ad9be409b27a2661d3
# dearpygui-2.3.1-cp312-cp312-win_amd64.whl
dearpygui==2.3.1 --hash=sha256:26ed9197cdb30099c665bd1b23724e0dba60ad06b71344ecca7e52748c21874b
# dearpygui-2.3.1-cp313-cp313-manylinux1_x86_64.whl
dearpygui==2.3.1 --hash=sha256:e3f64c8d4cae68a3b5be1b7531d08400ccbf1e4ff03c7acfc85954f98993f864
# dearpygui-2.3.1-cp313-cp313-manylinux2014_aarch64.whl
dearpygui==2.3.1 --hash=sha256:0d8b7a5a04cd4a6e25dbf162aa0405cf12143a1c82b33e371c20e5ba8d9349f3
# dearpygui-2.3.1-cp313-cp313-win_amd64.whl
dearpygui==2.3.1 --hash=sha256:7946722c50f1e08866dfdb78eb33dd4e67dea1a3cfe4400b159e1c96861116dc
# proxy_tools-0.1.0.tar.gz (nur sdist, kein Wheel)
proxy_tools==0.1.0 --hash=sha256:ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010
```
Three.js (npm): `three@0.187.0`, Integritaet laut Registry `sha512-Qiu7R+Cmh8CstZsY1uJOSWnVlfo7ZtNLV7mF8Jltk3LB3AtDu9cRZlcnRKkAk8Y4z6KKw35z7Y7Urd7jWY8etA==` (Tarball https://registry.npmjs.org/three/-/three-0.187.0.tgz). PixiJS: `pixi.js@8.22.0`, `sha512-QbTANHMZ751MIjLiLSUSM8a7LNMWwMIf0KbRCqlW+SPS9hNLfSVS+cl1O2SEp9g1K/wyLzj/OJHv+1TUfiPr/w==`. Eine lokale Kopie muss mit dieser Pruefsumme verglichen und eingecheckt werden; es gibt keinen CDN-Zugriff zur Laufzeit.
Fuer PySide6, Flet und die uebrigen Pakete: nicht erhoben (nicht empfohlen).

## Lizenzausschluss (AGPL/GPL)
- Weder Standardbibliothek, pywebview-Kette, Three.js, PixiJS (Hauptpaket), Dear PyGui noch Flet (Hauptpaket) sind AGPL/GPL.
- **PySide6 und shiboken6** bieten `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`: nur die LGPL-Option kame in Frage, und nur bei dynamischer Nutzung und mit ausdruecklicher Besitzerfreigabe -> ohne Freigabe `nicht nehmen`.
- **Flet** hat transitiv `certifi` (MPL-2.0, schwaches Copyleft): nur mit ausdruecklicher Besitzerfreigabe.
- PixiJS: Lizenzen der Unterabhaengigkeiten ungeprueft -> Ausschluss nicht belegt.
- AGPL/GPL-Komponenten waeren nur als getrennter Prozess denkbar; kein Kandidat ist darauf angewiesen.

## Entscheidung
nehmen
Besitzer-Freigabe: 2026-11-04

Freigabe durch den Besitzer im Chat am 2026-11-04: Ausschliesslich Stufe 1 (Python-Standardbibliothek `ThreadingHTTPServer`, lokaler Browser, Canvas 2D) fuer den Control-Center-Shell-Schritt `cc-shell`. Keine neue externe Bibliothek, keine Pflichtabhaengigkeit; `dependencies = []` bleibt. Die Schutzmassnahmen aus `docs/UI_CONTRACT.md` sind zwingend. pywebview, Three.js, PixiJS, PySide6, Flet und andere externe UI-Bibliotheken sind hiermit NICHT freigegeben und beduerfen eigener Pruefung/Freigabe. Windows-Nachweis bleibt erforderlich. Die Empfehlung unten braucht fuer Stufe 1 keine neue Abhaengigkeit.

### Empfehlung (ausdruecklich)
**Stufe 1 (empfohlen, null Abhaengigkeiten):** `ThreadingHTTPServer` aus der Standardbibliothek auf `127.0.0.1` (zufaelliger Port, Zufalls-Token, Host-/Origin-Pruefung, Limits) liefert die lokale Oberflaeche (HTML/CSS/JS aus dem Repository) und einen SSE-Strom nach `docs/UI_CONTRACT.md`; Befehle per POST. Gezeichnet wird mit **Canvas 2D**, das ist zugleich der Fallback fuer alle spaeteren Effekte. Oeffnung im Systembrowser (Edge ist auf Windows 10/11 vorhanden). Das erfuellt "moeglichst wenig Abhaengigkeiten", ist ohne Installation testbar und braucht keine Lizenzfreigabe.
**Stufe 2 (optional, erst nach eigener Besitzerfreigabe und eigenem Pruefschritt):** natives Fenster und Mini-Overlay ueber **pywebview 6.2.1** als optionales Extra (`[ui]`, Standard aus). BSD-3 ist zulaessig, aber: 7 zusaetzliche Pakete, ein aufgegebenes Paket (`proxy_tools`, 2014), Einzelbetreuer, nicht belegte Datenabfluss-Details. Vorher pruefen, ob ein Fenster ohne zusaetzliche Pakete ausreicht (z. B. Edge im App-Modus per Kommandozeile - **in dieser Sitzung nicht aus offizieller Quelle belegt, offen**).
**Stufe 3 (Premium V2, optional):** **Three.js 0.187.0** (MIT, keine Abhaengigkeiten) als lokal eingebettete Einzeldatei fuer den 3D-Kern, immer mit automatischem Wechsel auf Canvas 2D. Es gibt kein Netzwerk, keinen CDN-Zugriff.
**Nicht empfohlen:** Flet (MPL-2.0 transitiv, ungeklaerter Netzzugriff, junge 1.0-Reihe), PySide6 (LGPL nur mit Freigabe, > 120 MB, ausserhalb von "wenig Abhaengigkeiten"), PixiJS (10 ungeprueft Abhaengigkeiten, kein Vorteil gegenueber Canvas 2D/Three.js fuer diesen Zweck), Dear PyGui (MIT, keine Abhaengigkeiten, aber zweite, vom Vertrag/Web getrennte UI-Technik, keine Webansicht, kein Premium-3D-Pfad; bleibt Reserve).

## Pruefung (Datum und Quelle)
2026-11-04. Quellen: PyPI-JSON (https://pypi.org/pypi/<paket>/json fuer pywebview, pythonnet, clr_loader, cffi, pycparser, bottle, proxy_tools, typing_extensions, dearpygui, PySide6, PySide6-Essentials, PySide6-Addons, shiboken6, flet, flet-desktop, httpx, httpcore, anyio, certifi, idna, h11, msgpack, oauthlib, repath, packaging); npm-Registry (registry.npmjs.org/three, /pixi.js); LICENSE-Dateien auf raw.githubusercontent.com (pywebview 6.2.1, three.js dev, pixijs dev, DearPyGui v2.3.1, flet v1.0.5, pythonnet master, clr-loader master, bottle master); pywebview SECURITY.md/pyproject.toml/Doku (pywebview.flowrl.com: installation, web_engine, security, api); Microsoft Learn (WebView2: distribution, evergreen-vs-fixed-version, webview-features-flags, webdriver); nuget.org (Microsoft.Web.WebView2 1.0.4314.35); https://docs.python.org/3/library/http.server.html; MDN (Server-sent events, webglcontextlost, prefers-reduced-motion); https://www.qt.io/qt-licensing; https://doc.qt.io/qtforpython-6/licenses.html. Nicht erreichbar: GitHub-Seiten und -API der Fremd-Repositories (HTTP 403), Edge-Datenschutzseite (404). Fehlende Quellen sind oben als "unbekannt/offen" gefuehrt und nicht geschaetzt.

---

# Anhang A: Premium V2 - Vergleich

Alle Zeilen sind Dokumentations- bzw. Metadatenlage, **nicht gemessen** (kein Code erlaubt).

| Kriterium | Three.js / WebGL-3D | Canvas 2D (Fallback) | pywebview + WebView2 | Windows-Mini-Overlay |
|---|---|---|---|---|
| Abhaengigkeit | `three` 0.187.0, MIT, keine Unterpakete, lokal einzubetten | keine (Browserstandard) | 7 Python-Pakete + WebView2 Runtime | haengt vom Fenstermechanismus ab |
| Effekte | 3D, Shader, Partikel | 2D, Pegel, Wellen, Orb-Naeherung | nur Huelle fuer Web-Inhalt | nur kleiner Zustandsanzeiger |
| GPU-Ausfall | `webglcontextlost` (MDN) auslosen -> auf Canvas 2D wechseln; ohne GPU/mit `disable-gpu` ohne Software-Renderer startet der GPU-Prozess nicht (Microsoft-Doku) -> Erkennung beim Start (kein WebGL-Kontext) noetig | laeuft auch ohne GPU (Software) | Runtime fehlt -> Hinweis + Browserweg | wie Hauptansicht |
| Reduzierte Effekte | `prefers-reduced-motion` (MDN) + eigene Einstellung "Effekte: aus/reduziert/voll" | gleiche Schalter | -- | Standard: statisches Symbol |
| Windows-Eignung | WebGL in Edge/WebView2 laut Doku vorgesehen; real nicht geprueft | sicher | Evergreen auf Win 11 vorinstalliert, Win 10 "vast majority" | siehe unten |
| Lizenzrisiko | gering (MIT) | keines | BSD-3 (pywebview), Runtime-Lizenz ungeprueft | -- |

**Mini-Overlay (ca. 140x140, verschiebbar, optional Always-on-Top, Klick oeffnet Hauptfenster, nicht standardmaessig klickdurchlaessig):** Belegt durch die pywebview-API-Doku: `width/height`, `frameless=True`, `easy_drag=True` (verschiebbar durch Ziehen), `on_top`, mehrere Fenster moeglich, `focus=False` fuer nicht fokussierbar. Klick auf das Fenster kann ein Ereignis ausloesen, das das Hauptfenster oeffnet (eigene Logik, nichts Besonderes). **Einschraenkung:** `transparent` ist laut Doku "Not supported on Windows" -> das Overlay ist ein rechteckiges Fenster, kein rundes Orb-Overlay mit Transparenz. Klickdurchlaessigkeit (click-through) ist in der geprueften API **nicht vorgesehen**; das passt zur Vorgabe "nicht standardmaessig klickdurchlaessig", ein optionaler Modus waere ein eigener Windows-API-Zugriff (neuer Prueffall, ctypes, nicht freigegeben). Always-on-Top ist eine sichtbare Option (Standard aus), die Oberflaeche muss einen sichtbaren Notaus-Knopf behalten.

# Anhang B: Pruefbericht (Bewertung)

| Aspekt | Bewertung | Beleg |
|---|---|---|
| **Lokale Assets** | Moeglich und Pflicht: Three.js ist eine abhaengigkeitsfreie Einzeldatei (npm: keine `dependencies`), mit Registry-Integritaet pruefbar und einzuchecken; Canvas 2D braucht nichts; Schriften/Texturen lokal. Keine CDN-Aufrufe, CSP `default-src 'self'`. PixiJS bringt 10 npm-Abhaengigkeiten. | npm-Registry, LICENSE |
| **Performance** | **Nicht gemessen** (kein Code erlaubt). Dokumentationslage: Canvas 2D ist fuer Pegel/Wellen ausreichend; WebGL/Three.js ist teurer und GPU-abhaengig; SSE ohne HTTP/2 hat 6 Verbindungen/Host (MDN). Messung (Bildrate, CPU/GPU, RAM, Start) ist als Teil von `cc-voice-viz` einzuplanen; Budget und Abschaltung bei niedriger Bildrate vorab festlegen. | MDN, Microsoft-Doku |
| **Windows-GUI-Testbarkeit** | Stufe 1 gut: Server und Vertrag (`FakeUiBackend`, Schemas) ohne GUI testbar; DOM per Playwright (laut CLAUDE.md ein Windows-/CI-Thema). WebView2-Fenster: Microsoft beschreibt WebDriver-Tests ("Automate and test WebView2 apps with Microsoft Edge WebDriver"); pywebview selbst: **keine Testdoku geprueft (unbekannt)**. Tk/Fenster-Evidenz nur durch Windows-CI. **Windows-Nachweis ausstehend.** | Microsoft Learn |
| **Notaus-Erreichbarkeit** | Der Notaus darf nie von Browser/Fenster abhaengen. Vorgabe: (1) der Befehl `emergency_stop` ist laut Vertrag auch beim Notaus erlaubt; (2) jede Ansicht, auch das Mini-Overlay, zeigt einen immer sichtbaren Notaus-Knopf; (3) der bestehende globale Notaus (Tastenkombination/CLI/Tk-GUI) bleibt unabhaengig vom UI-Prozess; (4) bei Verbindungsverlust des Ereignisstroms zeigt die UI deutlich "getrennt", Rueckfragen werden laut Vertrag abgelehnt; (5) `reset_emergency` bleibt nur Anfrage. Ein abgestuerzter WebView2-Prozess darf den Notaus nicht verhindern. | `docs/UI_CONTRACT.md` |
| **Sicherheit** | Loopback + Token + Host/Origin + Limits Pflicht (`http.server` nur "basic security checks"). Keine pywebview-`js_api`-Bruecke, `debug` aus, keine Remote-Inhalte. Keine neue Autonomie: UI sendet nur Vertragsbefehle; es gibt keinen Befehl fuer Rechte/Tools. | Python-Doku, pywebview-Doku |
| **Lizenz** | Zulaessig ohne Freigabe: Stdlib (PSF), pywebview-Kette (BSD/MIT/MIT-0/PSF; proxy_tools MIT), Three.js (MIT), PixiJS (MIT, Unterbau ungeprueft), Dear PyGui (MIT), Flet-Hauptpaket (Apache-2.0). Freigabepflichtig: PySide6 (LGPL), Flet (certifi MPL-2.0). Runtime-Lizenz von WebView2: offen. | s. o. |

# Anhang C: Offene Fragen fuer den Besitzer

1. Soll Stufe 1 (Stdlib-Server, Systembrowser, Canvas 2D) als Control-Center-Basis fuer `cc-shell` gelten? (Empfehlung: ja.)
2. Soll fuer ein natives Fenster/Mini-Overlay ein eigener Pruefschritt fuer **pywebview** (optionales Extra, Standard aus) angelegt werden, trotz `proxy_tools` (2014, aufgegeben) und 7 Zusatzpaketen? Oder genuegt der Browser?
3. Ist ein **rechteckiges** Mini-Overlay akzeptabel (pywebview: `transparent` unter Windows nicht unterstuetzt)? Ist ein optionaler Click-through-Modus gewuenscht (dann eigener Windows-API-Schritt)?
4. Soll Three.js 0.187.0 (MIT) als lokal eingechecktes Asset fuer Premium V2 zugelassen werden (mit Pruefsumme, ohne CDN, mit Canvas-2D-Fallback)?
5. LGPL/MPL-2.0 (PySide6, Flet/certifi): freigeben oder dauerhaft ausschliessen? (Empfehlung: ausschliessen.)
6. WebView2-Runtime: Lizenzwortlaut und Umgang mit Windows 10 ohne Runtime (Hinweisdialog statt Installation?) klaeren; Edge-Datenschutz/Telemetrie ist nicht belegt.
7. Dokumentwiderspruch pywebview (.NET 4.0 vs. 4.6.2) und fehlende GitHub-Advisory-Pruefung: bei Freigabe mit erreichbarer Quelle nachholen (in dieser Sitzung GitHub gesperrt).
