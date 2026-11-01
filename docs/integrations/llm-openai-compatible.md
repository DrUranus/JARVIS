# OpenAI-kompatible HTTP-Schnittstelle (Ollama, LM Studio, llama.cpp-Server)

Pruefbericht nach `docs/INTEGRATIONS.md`, Schritt `llm-compat-vetting`. Geprueft wurde nur an offiziellen Quellen (Projekt-Repositories, LICENSE-Dateien, Release-Seiten, Herstellerdokumentation, Sicherheitsseiten). Es wurde nichts installiert, kein Code geschrieben oder geaendert und kein Server gestartet. Das Abrufwerkzeug lieferte teils **Zusammenfassungen statt Rohtext** (siehe Hinweise je Abschnitt); woertliche Zitate sind nur so weit belegt, wie sie hier in Anfuehrungszeichen stehen. Nicht Belegtes steht als "unbekannt" oder "offen".

## Name und Zweck
Gegenstand ist die **HTTP-Schnittstelle** `POST {base_url}/chat/completions` (OpenAI-Chat-Completions-Format) und drei lokale Server, die sie anbieten: **Ollama** (https://github.com/ollama/ollama), **LM Studio** (https://lmstudio.ai) und der **llama.cpp-Server** `llama-server` (https://github.com/ggml-org/llama.cpp). JARVIS soll damit einen lokalen oder selbst gehosteten Sprachmodell-Anbieter nutzen koennen (Datenschutz, Kosten, Offline-Betrieb), ohne neue Bibliothek: Es gibt keine Python-Abhaengigkeit, die Server laufen als **getrennte Prozesse**, JARVIS spricht nur HTTP mit der vorhandenen Schicht `src/jarvis/llm/http_providers.py` (`urllib`, `_post`).

Ist-Stand im Repository (gelesen, nicht geaendert): `OpenAIProvider` nimmt bereits `base_url` an und haengt `/chat/completions` an, **verlangt aber einen API-Schluessel** (`LLMError`, wenn leer), sendet immer `Authorization: Bearer`, hat **kein Streaming**, wertet das Fehlerformat nur als abgeschnittenen Text aus und kann keine Modellliste lesen. `_post` kommentiert "fixed https endpoints"; ein lokaler Server laeuft ueblicherweise ueber `http://127.0.0.1`.

## Lizenz (Wortlaut)
Je Server (keine Bibliothek, keine Lizenz fuer JARVIS-Code noetig; die Lizenz gilt fuer den getrennt installierten Server):

- **Ollama:** MIT. > "MIT License" / "Copyright (c) Ollama" / "Permission is hereby granted, free of charge, to any person obtaining a copy" (Fundstelle: https://raw.githubusercontent.com/ollama/ollama/main/LICENSE, abgerufen 2026-11-01; der Rest des Permission-Absatzes lag nur zusammengefasst vor: Nutzung, Kopie, Aenderung, Weitergabe, Verkauf ohne Einschraenkung, Lizenzhinweis muss beiliegen). Die Repository-Seite zeigt ebenfalls "MIT license".
- **llama.cpp (llama-server):** MIT. > "MIT License" / "Copyright (c) 2023-2026 The ggml authors" / "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:" (Fundstelle: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/LICENSE, abgerufen 2026-11-01). Lizenz der mitgelieferten `vendor`-Teile und der Modellgewichte: nicht geprueft, **offen**.
- **LM Studio (Desktop-App): proprietaer, kein Open Source.** > "non-exclusive, non-transferable license to use the Software solely for Your personal and / or internal business purposes" und die Software sei "the exclusive property of Company and its suppliers"; untersagt sind u. a. Aendern/Ableiten ("modify, adapt, alter, translate, or create derivative works"), Weitergabe/Verkauf ("sublicense, distribute, sell, use for service bureau use") und Zerlegen ("reverse engineer, decompile, disassemble") (Fundstelle: https://lmstudio.ai/terms, "Version: August 23, 2026", Vertragspartner Element Labs, Inc., abgerufen 2026-11-01; Zitate aus der Zusammenfassung des Abrufwerkzeugs). Das Pruefschema erlaubt nur permissive Lizenzen **fuer Bibliotheken, die in JARVIS gelangen**; LM Studio gelangt nie in das Repository und wird nie weitergegeben, sondern vom Besitzer selbst installiert. Das ist **keine Einbindung**, aber die Nutzungsbedingungen sind vom Besitzer zu akzeptieren (offene Frage 3). Die Befehlszeile `lms` ist laut Repository MIT (https://github.com/lmstudio-ai/lms, "MIT license"); sie wird hier nicht gebraucht.
- **Die Schnittstelle selbst:** Die OpenAPI-Beschreibung des Herstellers steht unter MIT (> "This project is licensed under the MIT License." Fundstelle: https://github.com/openai/openai-openapi, README, abgerufen 2026-11-01). Das ist die Lizenz der Beschreibung, nicht eine Lizenz fuer fremde Server.

## Version und Datum
Stand der Seiten am 2026-11-01. Jahreszahlen fehlen auf mehreren Seiten (GitHub zeigt "28 Oct"); das Jahr ist dort Annahme (2026).

| Server | letzte Version laut offizieller Seite | Datum | Quelle |
|---|---|---|---|
| Ollama | v0.40.13 (als "Latest" markiert); davor v0.40.12 (27 Oct), v0.40.11 (24 Oct), v0.40.10 (23 Oct) | 28 Oct (Jahr nicht angezeigt) | https://github.com/ollama/ollama/releases |
| llama.cpp | b12032 (fortlaufende Build-Nummer, kein Semver); davor b12031, b12030, b12029 am selben Tag | 01 Nov (Jahr nicht angezeigt), 09:00 | https://github.com/ggml-org/llama.cpp/releases |
| LM Studio | **nicht belegt**: die abgerufene Aenderungsseite https://lmstudio.ai/changelog nannte "Bionic 1.1.10" (29 Oct 2026); ob das die Hauptanwendung bezeichnet, ist aus der Antwort nicht eindeutig | - | https://lmstudio.ai/changelog |
| OpenAI-API-Beschreibung | `info.version: 2.3.0`, `servers: https://api.openai.com/v1` | Datum nicht erhoben | https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml (nur die ersten 100000 von rund 4,2 Mio. Zeichen gelesen) |

## Pflege
- **Ollama:** Repository oeffentlich, nicht archiviert, rund 5962 Commits laut Seite, vier Veroeffentlichungen in sechs Tagen (23. bis 28. Oct). Aktiv gepflegt. Sicherheitsseite: "There aren't any published security advisories." (Fundstelle: https://github.com/ollama/ollama/security/advisories). Fehlende Advisories heissen nicht, dass es keine Schwachstellen gibt; eine Sicherheitsrichtlinie wurde nicht gelesen (**offen**).
- **llama.cpp:** nicht archiviert, mehrere Builds pro Tag; Betreuer ggerganov (Advisories) und das ggml-Projekt. Sicherheitsrichtlinie (https://github.com/ggml-org/llama.cpp/blob/master/SECURITY.md): "The private security disclosure program is disabled until further notice"; Meldungen als oeffentliche Pull Requests; Denial-of-Service gilt in der Regel nicht als Schwachstelle; Web-UI, experimentelle Funktionen sowie Router und MCP sind vom Geltungsbereich ausgenommen. Das heisst: die Behandlung von Sicherheitsmeldungen ist eingeschraenkt.
- **LM Studio:** Anbieter Element Labs, Inc.; geschlossene Entwicklung, Pflege nur ueber die Aenderungsseite beurteilbar (Eintraege Oct 2026, 1.1.7 bis 1.1.10); Sicherheitsseite/Advisories nicht geprueft, **offen**.
- Eine Wartungsaussage zur OpenAI-Beschreibung (Pflegeintervall) wurde nicht erhoben; offen.

## Python- und Windows-Kompatibilitaet
- **Python:** Es kommt keine Python-Abhaengigkeit hinzu; `urllib` aus der Standardbibliothek genuegt (Projekt: Python >= 3.11).
- **Ollama unter Windows:** laut README Installation per PowerShell-Skript (`irm https://ollama.com/install.ps1 | iex`) oder manueller Download `OllamaSetup.exe`; ein `.exe` stand in den sichtbaren Release-Anhaengen nicht (nur `install.ps1`; 8 von 19 Anhaengen verborgen). Standard-Bind laut FAQ: > "Ollama binds 127.0.0.1 port 11434 by default. Change the bind address with the `OLLAMA_HOST` environment variable." Modellordner unter Windows `C:\Users\%username%\.ollama\models` (`OLLAMA_MODELS` verlegt ihn). (Fundstelle: https://docs.ollama.com/faq.)
- **LM Studio unter Windows:** Desktop-App; Basis-URL `http://localhost:1234/v1` (Beispiele der Doku; Standardport nicht ausdruecklich genannt). Die Aenderungsseite nennt Windows-Eintraege (Windows on ARM, CUDA 13). Der Server wird in der App gestartet (Reiter Developer); ob ein Dienstbetrieb ohne Oberflaeche moeglich ist, ist **offen**.
- **llama.cpp unter Windows:** Release-Anhaenge b12032: `llama-b12032-bin-win-cpu-x64.zip`, `...-win-cpu-arm64.zip`, `...-win-cuda-12.4-x64.zip`, `...-win-cuda-13.4-x64.zip`, `...-win-vulkan-x64.zip` (sowie arm64-Varianten und getrennte `cudart-...`-Pakete). Standard laut Server-README: `--host 127.0.0.1`, Port in der gelesenen README-Fassung `9931` (> "listens on `127.0.0.1:9931`"; weicht von dem ab, was haeufig genannt wird; vor dem Einbau am installierten Binary mit `--help` pruefen). Der Server ist ein Konsolenprogramm; Windows-Dienst/Autostart ist nicht Teil der Pruefung.
- Ein Linux-Lauf ist kein Windows-Nachweis. Hier lief nichts; Windows-Nachweis fuer einen spaeteren Provider kommt nur aus einem Windows-Test mit einem **Test-Server im Prozess** (Stub), nicht aus einem echten Modell.

## Transitive Abhaengigkeiten
Keine fuer JARVIS: kein neues Python-Paket. Die Server sind getrennte Programme mit eigenen (nicht geprueften) Abhaengigkeiten; sie werden nicht in JARVIS eingebunden. llama.cpp enthaelt ein Verzeichnis `vendor` mit Fremdcode (SECURITY.md); dessen Lizenzen wurden **nicht** geprueft (offen, betrifft nur den Betrieb des getrennten Servers).

## Schnittstellen-Vergleich (Endpunkte, Streaming, Fehler, Authentisierung)

| Punkt | OpenAI-Beschreibung (2.3.0) | Ollama | LM Studio | llama-server |
|---|---|---|---|---|
| Basis-URL (lokal) | `https://api.openai.com/v1` | `http://localhost:11434/v1/` | `http://localhost:1234/v1` | `http://127.0.0.1:<Port>/v1` (Port siehe oben) |
| `/chat/completions` | ja | ja | ja | ja (> "Given a ChatML-formatted json description in `messages`, it returns the predicted completion.") |
| `/models` | ja | ja (`/v1/models`, `/v1/models/{model}`) | ja (`GET /v1/models`) | ja (> "Returns information about the loaded model.") |
| `/completions`, `/embeddings` | ja | ja | ja | `/v1/completions` ja; `/v1/embeddings` in der gelesenen Seite nicht sichtbar (nur 100000 von 135851 Zeichen gelesen) |
| `/responses` | ja | ja, nur zustandslos | ja | nicht sichtbar |
| Streaming | `stream: true`, Ende mit dem Klartext `[DONE]` (Spezifikation: "`[DONE]` is literal text", kein JSON-Chunk) | ja (`stream`, `stream_options.include_usage`) | auf der gelesenen Seite nicht erwaehnt, **offen** | ja, Server-Sent-Events (Parameter `stream`) |
| Authentisierung | `Authorization: Bearer` (Schema `ApiKeyAuth`, Einzelheiten nicht gelesen) | lokal: > "The client requires an API key value, but Ollama ignores it."; Cloud (`https://ollama.com/v1`): Schluessel in `OLLAMA_API_KEY` | Standard: > "By default, LM Studio does not require authentication for API requests."; optional Token, dann `Authorization: Bearer $LM_API_TOKEN` | optional `--api-key KEY` / `--api-key-file` / Umgebungsvariable `LLAMA_API_KEY`; `/health` ist ausgenommen > "This endpoint is public (no API key check)." |
| Fehlerformat | `Error`-Schema nicht gelesen (**offen**) | allgemeines Fehlerformat nicht dokumentiert (nur 400 bei nicht unterstuetzten Sprachwerten) | nicht dokumentiert (gelesene Seite) | Beispiel: `{"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}}` |
| Nicht unterstuetzt | - | Chat: logprobs, `tool_choice`, `logit_bias`, `user`, `n`, Bild-URLs (nur Base64) | nicht aufgelistet | nicht abschliessend gelesen |

Folgerungen fuer einen Provider (nur Entwurf, kein Code): Der kleinste gemeinsame Nenner ist `POST /chat/completions` mit `model`, `messages`, `temperature`, `max_tokens`, Antwort `choices[0].message.content` und `usage`; das deckt der vorhandene `OpenAIProvider` bereits ab. Was fehlt: (1) Schluessel **optional** (Ollama ignoriert ihn, LM Studio und llama-server standardmaessig ohne), (2) `http://` nur fuer Loopback zulassen, (3) Fehlerkoerper beider Formen (`{"error": {"message": ...}}`) lesbar machen, (4) kein `max_tokens`-/`max_completion_tokens`-Konflikt: die gelesenen Seiten von Ollama und llama-server nennen `max_tokens`; die OpenAI-Seite (HTTP 403 fuer die Referenz) wurde nicht gelesen, das Verhalten fuer `max_completion_tokens` ist daher **offen**, (5) Streaming ist **nicht noetig** fuer die bisherigen Aufrufer (`complete` liefert eine fertige Antwort) und kann spaeter mit `urllib` (zeilenweise Server-Sent-Events, Ende bei `[DONE]`) ergaenzt werden, (6) lange Zeitlimits, weil lokale Modelle beim ersten Aufruf laden (Ollama, llama-server liefern waehrenddessen 503 "Loading model").

## Sicherheitshinweise
- **Netzbindung:** Alle drei Server binden standardmaessig an Loopback (Ollama `127.0.0.1:11434`, llama-server `127.0.0.1`, LM Studio `localhost`). Wer sie mit `OLLAMA_HOST`/`--host` im Netz freigibt, hat ohne Schluessel eine offene Modell-Schnittstelle. llama-server-README: "By default the server reflects any `Origin` header back with credentials allowed." und empfiehlt fuer oeffentliche Betriebe einen API-Schluessel und einen Reverse-Proxy. JARVIS darf nur Loopback-Ziele ohne ausdrueckliche Besitzer-Konfiguration zulassen.
- **llama-server:** `--tools`, `--agent`, `--mcp-servers-config`, `--ui-mcp-proxy` "exposes file read/write over the API" bzw. fuehren Befehle mit den Rechten des Servers aus ("The child process runs with the same privileges as the server"). **Diese Optionen duerfen nie aktiviert werden**, wenn JARVIS den Server nutzt.
- **Advisories llama.cpp** (https://github.com/ggml-org/llama.cpp/security/advisories, erste Seite von mindestens zwei, Zusammenfassung des Abrufwerkzeugs; CVE-Kennungen und betroffene/behobene Versionen lagen nicht vor): u. a. "Unauthenticated RCE via GRAPH_COMPUTE buffer=0 bypass in llama.cpp RPC backend" (GHSA-j8rj-fmpv-wcxw, 2026-03-26, Critical), mehrere Heap-Ueberlaeufe beim Parsen von GGUF-Modelldateien (High; 2025-06 bis 2026-03) und "Out-of-bounds Write in llama.cpp llama-server" (GHSA-8947-pfff-2f3c, 2026-01-05, Low). Folge: nur Binaries der aktuellen Version, **keine fremden Modelldateien** laden (SECURITY.md verlangt dafuer Isolierung), den RPC-Server nicht nutzen. Ob die genannten Fehler in der gepruefen Version b12032 behoben sind, wurde **nicht** festgestellt (offen).
- **Ollama:** keine veroeffentlichten Advisories (Stand 2026-11-01). Bekannte Probleme, die dort nicht als Advisory stehen, wurden nicht gesucht (Pruefung nur an den vorgegebenen Quellen).
- **LM Studio:** geschlossener Code, keine Quelleinsicht; Advisories nicht geprueft.
- **Installation:** Die Ollama-Anleitung nutzt `irm ... | iex` (Skript aus dem Netz, direkt ausgefuehrt). JARVIS fuehrt das nie aus; der Besitzer entscheidet selbst (Download des Installers mit Pruefsumme ist die vorsichtigere Wahl).
- **Prompt-Injection/Autonomie:** Die Antwort eines Modells bleibt unvertrauter Text; Tool-Aktionen laufen weiter nur ueber `ToolRegistry.execute` -> `PermissionEngine`. Ein lokaler Provider aendert daran nichts und darf keine Tools "serverseitig" ausfuehren (`tools`-Felder der Server werden nicht genutzt).

## Datenabfluss
- **Lokaler Betrieb (empfohlen):** Prompt und Antwort bleiben auf dem Rechner, solange der Server auf Loopback laeuft und kein Cloud-Modell gewaehlt ist. Ollama (FAQ): > "Ollama runs locally. We don't see your prompts or data when you run locally." LM Studio (Datenschutzrichtlinie, "Effective June 2026"): > "none of your messages, chat histories, and documents are ever transmitted from your system" und > "the application does not include telemetry or user-specific tracking". llama.cpp: kein Telemetriehinweis in den gelesenen Seiten; **unbekannt**, nicht geprueft.
- **Was dennoch ins Netz geht:** (a) **Modell-Downloads** (Ollama `ollama pull` aus der Ollama-Registry, LM Studio Modellsuche/Download, llama-server `-hf <user>/<model>` von Hugging Face; `--offline` verhindert das, `-hft`/`HF_TOKEN` waere ein Schluessel), (b) **Update-Pruefungen** (LM Studio: laut Richtlinie gehen dabei App-Version, Build, Betriebssystem und IP-Adresse an den Anbieter), (c) **Ollama-Konto-/Cloud-Funktionen**: Cloud-Modelle und Websuche senden Prompts an `ollama.com`; abschaltbar mit `OLLAMA_NO_CLOUD=1` oder `disable_ollama_cloud` in `~/.ollama/server.json` (FAQ). Zu Ollama sagt die FAQ "basic account info and limited usage metadata" werde zur Diensterbringung erhoben; eine ausdrueckliche Aussage zu Telemetrie des lokalen Programms fehlt in den gelesenen Seiten (**unbekannt**).
- **Cloud-Anbieter:** Zeigt `base_url` auf `https://api.openai.com/v1` (oder ein anderes entferntes Ziel, auch `https://ollama.com/v1`), gehen Prompt-Inhalte, bei `memory.use_in_prompts = true` auch Erinnerungen, an den Anbieter. Das gilt schon heute fuer `provider = "openai"` und wird nicht schlimmer. Bei einem lokalen Provider ist das Ziel Loopback; eine Konfiguration mit entferntem Ziel muss im Provider klar als "Cloud" erkennbar sein (Warnung in `jarvis doctor`, Vorschlag).
- Speicherorte: Ollama `%USERPROFILE%\.ollama\models` (Modelle, gross); LM Studio und llama.cpp: nicht erhoben.

## Pinning mit Hash
Entfaellt: Es wird kein Paket installiert und nichts in `pyproject.toml` aufgenommen. Fuer die Server selbst (vom Besitzer installiert) gilt: Version und Pruefsumme des Installers/ZIP beim Herunterladen notieren (Ollama v0.40.13, llama.cpp b12032 am Pruefdatum); Hashes wurden hier nicht erhoben.

## Lizenzausschluss (AGPL/GPL)
Es wird kein Code eingebunden. Keiner der drei Server ist AGPL/GPL: Ollama MIT, llama.cpp MIT (jeweils im LICENSE-Wortlaut belegt, siehe oben). LM Studio ist proprietaer (Nutzungsbedingungen) und laeuft ausschliesslich als **getrennter Prozess ohne Einbindung**; JARVIS kommuniziert nur ueber HTTP und liefert die Software nicht aus. Die Lizenzen der mitgelieferten Fremdteile der Server (z. B. llama.cpp `vendor`) wurden nicht geprueft; da die Server nicht verteilt oder eingebunden werden, entsteht daraus fuer JARVIS keine Lizenzpflicht, dies ist aber **nicht rechtlich geprueft**.

## Entscheidung
nehmen

Gemeint ist: **ein OpenAI-kompatibler Provider ohne neue Bibliothek, mit der vorhandenen HTTP-Schicht** (`urllib`), als Weiterentwicklung von `OpenAIProvider` (Empfehlung bestaetigt, nicht verworfen). Es wird weder eine Bibliothek aufgenommen noch ein Server mitgeliefert.

Begruendung:
- Die Schnittstelle `POST /chat/completions` ist bei allen drei Servern belegt (Ollama-Doku, LM-Studio-Doku, llama-server-README) und deckt sich mit der Hersteller-Beschreibung; der vorhandene Provider spricht sie schon.
- Keine neue Abhaengigkeit, keine transitiven Lizenzen, kein Hash-Pinning, kein Datenabfluss durch eine Bibliothek.
- Ollama und llama.cpp sind MIT; LM Studio ist proprietaer, wird aber nur vom Besitzer separat installiert.
- Standardmaessig bleiben Daten lokal (Loopback), Cloud nur durch ausdrueckliche Konfiguration.

Empfohlene Rangfolge der Server (Empfehlung, Besitzer entscheidet): 1. **Ollama** (MIT, Windows-Installer, einfache Verwaltung, Standard Loopback, Cloud abschaltbar); 2. **llama-server** (MIT, schlank, aber Konsolenprogramm, die gelesene README nennt viele zu meidende Optionen und mehrere Advisories zu Modell-Parsern); 3. **LM Studio** (proprietaer, komfortabel, Authentisierung standardmaessig aus).

Bedingungen fuer den Folgeschritt `llm-compat-provider` (nicht Teil dieses Auftrags):
1. Schluessel optional bei Loopback, Pflicht bei entferntem Ziel; `http://` nur fuer `127.0.0.1`/`localhost`/`::1`.
2. Kein Streaming im ersten Schnitt; Fehlerkoerper beider Formen lesbar; lange, konfigurierbare Zeitlimits.
3. Kein Vermischen von `provider = "openai"` (Cloud) und lokalem Provider in der Anzeige: Datenschutzwarnung in `jarvis doctor` bei entferntem Ziel.
4. Tests nur mit einem Stub-Server auf Loopback im Testprozess, kein Netz, kein echtes Modell; Windows-Nachweis nur ueber den CI-Windows-Lauf.
5. Verdrahtung nur in `src/jarvis/bootstrap.py`; Standard `provider = "mock"` bleibt, keine Sicherheitsdefaults aendern.

Offene Fragen an den Besitzer:
1. Welcher Server soll der Standard sein (Empfehlung Ollama)? Welches Modell und welche Hardware (GPU)?
2. Duerfen Cloud-Ziele (z. B. OpenAI, Ollama-Cloud) ueberhaupt in der Konfiguration stehen, oder nur Loopback?
3. LM Studio: Sind die Nutzungsbedingungen (privat/intern, Stand 2026-08-23) fuer den Einsatz akzeptabel?
4. Soll der Provider Streaming bekommen (Sprachausgabe waehrend der Erzeugung)? Das ist ein eigener Schritt.
5. Soll `jarvis doctor` einen laufenden lokalen Server erkennen (nur Loopback-Anfrage `GET /v1/models`)?
6. Nicht erhoben und vor dem Einbau nachzupruefen: Fehlerformat und `max_completion_tokens` laut OpenAI-Spezifikation (Komponentenabschnitt), Port-Standard von llama-server (README nennt 9931), Behebungsstand der llama.cpp-Advisories in der verwendeten Version, Sicherheitsrichtlinie und Advisories von LM Studio, Hash/Signatur der Windows-Installer.

## Pruefung (Datum und Quelle)
2026-11-01. Quellen (alle am Pruefdatum abgerufen; das Abrufwerkzeug fasst Seiten teils zusammen):
- https://raw.githubusercontent.com/ollama/ollama/main/LICENSE
- https://github.com/ollama/ollama (README-Auszug), https://github.com/ollama/ollama/releases, https://github.com/ollama/ollama/security/advisories
- https://docs.ollama.com/api/openai-compatibility, https://docs.ollama.com/faq (die Datei `docs/openai.md` im Repository lieferte 404)
- https://raw.githubusercontent.com/ggml-org/llama.cpp/master/LICENSE, https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md (nur Zeichen 0 bis 100000 von 135851), https://github.com/ggml-org/llama.cpp/releases, https://github.com/ggml-org/llama.cpp/security/advisories (erste Seite), https://github.com/ggml-org/llama.cpp/blob/master/SECURITY.md
- https://lmstudio.ai/docs/developer/openai-compat, https://lmstudio.ai/docs/developer/core/authentication, https://lmstudio.ai/terms, https://lmstudio.ai/privacy, https://lmstudio.ai/changelog, https://github.com/lmstudio-ai/lms
- https://github.com/openai/openai-openapi (README), https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml (nur Anfang gelesen)
- Nicht erreichbar: https://platform.openai.com/docs/api-reference/chat/create (HTTP 403). Als Ersatz diente die offizielle OpenAPI-Beschreibung desselben Herstellers; deren Komponentenabschnitt (Fehlerschema, Sicherheitsschema, `stream`-Beschreibung) wurde nicht gelesen, daher die offenen Punkte oben. Alle Kern-Endpunkte und Lizenzen liegen aus den Hauptquellen der drei Server belegt vor, deshalb wird der Schritt nicht als `blocked` gefuehrt; der Besitzer kann das abweichend werten.
- Repository (gelesen): `src/jarvis/llm/http_providers.py`, `src/jarvis/config.py`, `config/jarvis.toml`, `docs/INTEGRATIONS.md`, `docs/BACKLOG.md`.

## Umsetzung (Schritt `llm-compat-provider`)
Umgesetzt in `src/jarvis/llm/openai_compatible.py` (Provider `openai_compatible`, nur `urllib`, keine neue Bibliothek), registriert in `llm/factory.py`; `llm.allow_remote` (Standard `false`) in `config.py`. Standard-Provider bleibt `mock`. Bedingungen 1, 2, 4 und 5 sind erfuellt (Schluessel optional bei Loopback, Pflicht bei Remote; `http` nur Loopback; Fehlerkoerper beider Formen; Fake-Transport statt Netz; die Verdrahtung laeuft ueber die bestehende Fabrik, `bootstrap.py` brauchte keine Aenderung). Nicht umgesetzt: Warnung in `jarvis doctor` (Bedingung 3) und Streaming. Tests: `tests/test_llm_openai_compatible.py`. Windows-Nachweis steht aus (CI).
