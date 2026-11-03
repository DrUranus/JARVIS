# Lokale Spracherkennung (STT) fuer Windows: faster-whisper, whisper.cpp, Vosk, Silero-VAD

Pruefbericht nach `docs/INTEGRATIONS.md`, Schritt `stt-vetting`. Geprueft wurde nur an offiziellen Quellen (Projekt-Repositories und LICENSE-Dateien, Modellseiten auf huggingface.co und alphacephei.com, PyPI-Seiten der Projekte, Advisories-Seiten). Es wurde **nichts installiert, kein Code geschrieben, kein Modell gespeichert**. Hinweis zur Ehrlichkeit: Beim Pruefen wurden zwei kleine Dateien (je rund 2 MB: `silero_vad.onnx` aus dem Silero-Repository und `silero_vad_v6.onnx` aus dem faster-whisper-Repository) nur auf den Statuscode geprueft und direkt nach `/dev/null` geschrieben; es blieb nichts auf der Platte, es wurde nichts geladen oder ausgefuehrt. Von den Modellen wurden nur Metadaten (Hugging-Face-API, Modellliste von Vosk, HTTP-Kopfzeilen) gelesen. Das Abrufwerkzeug lieferte bei GitHub-HTML-Seiten teils Zusammenfassungen; Rohdateien (LICENSE, README) und PyPI-JSON wurden dagegen im Volltext gelesen. Nicht Belegtes steht als "unbekannt" oder "offen".

## Name und Zweck
JARVIS soll gesprochene Sprache **lokal** (offline, ohne Cloud, ohne API-Schluessel) in Text umsetzen. Heute gibt es nur den Cloud-Anbieter `openai` (Whisper-API) und `mock` (README, Abschnitt Voice). Geprueft werden vier Kandidaten:

| Kandidat | Art | Projekt |
|---|---|---|
| **faster-whisper** (mit **CTranslate2**) | Python-Bibliothek + native Laufzeit | https://github.com/SYSTRAN/faster-whisper, https://github.com/OpenNMT/CTranslate2 |
| **whisper.cpp** | C/C++-Programm bzw. Bibliothek (hier: getrennter Prozess) | https://github.com/ggml-org/whisper.cpp |
| **Vosk** | Kaldi-basierte Bibliothek (`vosk-api`) | https://github.com/alphacep/vosk-api, Modelle: https://alphacephei.com/vosk/models |
| **Silero-VAD** | Sprachaktivitaetserkennung (nur Pausen/Sprache, keine Texterkennung) | https://github.com/snakers4/silero-vad |

Ergebnis ist **nur dieses Dokument**. Die Schnittstelle `STTProvider` (`src/jarvis/voice/base.py`) existiert bereits; ein Einbau waere ein eigener, spaeter freizugebender Schritt.

## Lizenz (Wortlaut)
Gepruefter Tag: 2026-11-03. Je Kandidat **Code** und **Modelle** getrennt.

**Code**
- **faster-whisper: MIT.** > "MIT License" / "Copyright (c) 2023 SYSTRAN" / "Permission is hereby granted, free of charge, to any person obtaining a copy" (Fundstelle: https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/LICENSE). PyPI: "MIT", Klassifikator `License :: OSI Approved :: MIT License` (https://pypi.org/pypi/faster-whisper/json, 1.2.1).
- **CTranslate2: MIT.** > "MIT License" / "Copyright (c) 2018-     SYSTRAN." / "Copyright (c) 2019-     The OpenNMT Authors." (Fundstelle: https://raw.githubusercontent.com/OpenNMT/CTranslate2/master/LICENSE; PyPI 4.8.5: "MIT").
- **whisper.cpp: MIT.** > "MIT License" / "Copyright (c) 2023-2026 The ggml authors" (Fundstelle: https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/LICENSE). Mitgelieferte Fremdteile (ggml-Backends) wurden nicht einzeln geprueft: offen.
- **Vosk (vosk-api): Apache-2.0.** > "Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/" (Fundstelle: https://raw.githubusercontent.com/alphacep/vosk-api/master/COPYING, 176 Zeilen). Die Python-Metadaten auf PyPI (0.3.45) haben ein leeres Lizenzfeld, nur den Klassifikator "Apache Software License"; massgeblich ist die COPYING-Datei.
- **Silero-VAD: MIT.** > "MIT License" / "Copyright (c) 2020-present Silero Team" (Fundstelle: https://raw.githubusercontent.com/snakers4/silero-vad/master/LICENSE). Die README zeigt ein Abzeichen mit dem Alt-Text "License: CC BY-NC 4.0", dessen sichtbarer Text aber "MIT" lautet (https://github.com/snakers4/silero-vad, README Zeile 1); der LICENSE-Text und die PyPI-Klassifikation (`MIT License`) sind eindeutig MIT. Widerspruch in der README: offen fuer den Besitzer zur Kenntnis (siehe Fragen).

**Modelle (Gewichte)** - getrennt vom Code lizenziert; hier der Befund je Modell:
- **Whisper-Gewichte (OpenAI) und die darauf beruhenden Umwandlungen:** > "Whisper's code and model weights are released under the MIT License. See LICENSE for further details." (Fundstelle: https://raw.githubusercontent.com/openai/whisper/main/README.md, Zeile 160; LICENSE: "MIT License / Copyright (c) 2022 OpenAI"). Umwandlungen: `Systran/faster-whisper-{tiny,base,small,medium,large-v3}` und `Systran/faster-distil-whisper-large-v3` tragen auf Hugging Face das Lizenz-Tag `mit` (https://huggingface.co/api/models/Systran/faster-whisper-small usw.). `ggerganov/whisper.cpp` (ggml-Dateien) traegt `mit` (https://huggingface.co/api/models/ggerganov/whisper.cpp). `openai/whisper-small` traegt dort dagegen `apache-2.0` (https://huggingface.co/api/models/openai/whisper-small): **die Hersteller-Angaben sind nicht einheitlich** (MIT in README/LICENSE, Apache-2.0 auf dem Hugging-Face-Eintrag). Beides ist permissiv. Die Lizenz der **Trainingsdaten** von Whisper nennt keine der gelesenen Quellen: offen.
- **Vosk-Modelle:** Die offizielle Modelltabelle (https://alphacephei.com/vosk/models) nennt je Modell eine Lizenz: `vosk-model-de-0.21` und `vosk-model-small-de-0.15` **Apache 2.0**; `vosk-model-de-tuda-0.6-900k` **Apache 2.0**; `vosk-model-small-de-zamia-0.3` **LGPL-3.0** (dort "not recommended") - ausgeschlossen. Dieselbe Tabelle fuehrt ein franzoesisches Modell mit **AGPL** (nicht verwendet). Die Lizenz der Trainingsdaten der deutschen Modelle steht auf der Tabelle nicht: offen.
- **Silero-VAD-Modell:** > "Published under permissive license (MIT) Silero VAD has zero strings attached - no telemetry, no keys, no registration, no built-in expiration, no keys or vendor lock." (Fundstelle: README Zeile 137). Das Modell liegt als `silero_vad.onnx` im Repository und im Python-Paket (Groesse laut HTTP-Antwort 2 327 524 Byte). Trainingsdaten: README nennt "over 6000 languages"; Lizenz der Daten: offen.

## Version und Datum
Stand 2026-11-03 laut PyPI-Seiten des Projekts (Zeitstempel UTC):

| Paket | Version | veroeffentlicht |
|---|---|---|
| faster-whisper | 1.2.1 | 2025-10-31 (Vorgaenger 1.2.0: 2025-08-06) |
| ctranslate2 | 4.8.5 | 2026-11-02 |
| onnxruntime (fuer VAD) | 1.31.1 | 2026-10-26 |
| vosk | 0.3.45 | 2022-12-14 (Vorgaenger 0.3.44: 2022-09-25) |
| silero-vad | 6.2.3 | 2026-09-23 |
| pywhispercpp (Dritt-Bindung an whisper.cpp, **nicht** vom Projekt selbst) | 1.5.1 | 2026-08-22 |
| whisper.cpp | v1.9.5, "Latest", Wartungsrelease "Updates to ggml v0.26.0" | "06 Oct" ohne Jahresangabe; Jahr 2026 ist Annahme (https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5) |

Hinweis: Auf PyPI gibt es **keine** Veroeffentlichung von whisper.cpp selbst. Eine Python-Bindung ist hier nicht Gegenstand (fremdes Paket, MIT, nur als Hinweis); whisper.cpp wird als getrennter Prozess beurteilt.

## Pflege
- **faster-whisper:** Repository oeffentlich, nicht archiviert, 275 Commits, 6 offene Issues (GitHub-Seite, 2026-11-03). Letzte Veroeffentlichung vor 12 Monaten (2025-10-31), davor August 2025 und Januar 2025: ein **langsamer, aber nicht eingeschlafener** Takt. Die Releases-Liste der GitHub-Seite war im Abruf leer; Datum des letzten Commits: nicht belegt.
- **CTranslate2:** sehr aktiv (vier Veroeffentlichungen vom 2026-08-31 bis 2026-11-02: 4.8.2, 4.8.3, 4.8.4, 4.8.5). Betreuer ist SYSTRAN (wie bei faster-whisper).
- **whisper.cpp:** nicht archiviert, laufende Wartungsreleases, grosse Entwicklergemeinde (ggml). Sicherheitsrichtlinie `SECURITY.md` dieses Repositories: **nicht gelesen** (Abruf lieferte nichts): offen.
- **Vosk:** Repository 537 Commits, nicht als archiviert gekennzeichnet; **die letzte PyPI-Veroeffentlichung ist fast vier Jahre alt (2022-12-14)**. Die Wartung ist daher schwach belegt; Releases-Liste auf GitHub leer, Datum des letzten Commits nicht belegt. Die Modelle `de-0.21` (HTTP `Last-Modified: 2021-09-14`) und `small-de-0.15` (`Last-Modified: 2020-12-03`) sind **5 bzw. 6 Jahre alt**.
- **Silero-VAD:** 592 Commits, mehrere Veroeffentlichungen 2025/2026 (6.2.0 2025-11-06, 6.2.1 2026-02-24, 6.2.2 2026-09-17, 6.2.3 2026-09-23). Aktiv.
- **Sicherheitsmeldungen:** Die Advisories-Seiten von `SYSTRAN/faster-whisper` und `ggml-org/whisper.cpp` zeigen beide "There aren't any published security advisories." (2026-11-03). Fehlende Advisories heissen nicht, dass es keine Schwachstellen gibt. Fuer CTranslate2, Vosk und Silero-VAD wurden die Advisories-Seiten **nicht** gelesen: offen.

## Python- und Windows-Kompatibilitaet
Projekt verlangt Python >= 3.11 und Windows als Zielsystem. Ein Linux-Lauf ist kein Windows-Nachweis; hier lief **nichts**, alle Angaben stammen aus Registerdaten.
- **faster-whisper 1.2.1:** reine Python-Wheel `py3-none-any` (kein Windows-spezifischer Teil), `requires_python >=3.9`. Die Windows-Eignung haengt an den Abhaengigkeiten: **ctranslate2 4.8.5** hat Windows-Wheels `win_amd64` fuer cp39, cp310, **cp311**, cp312, cp313, cp314, cp314t, cp315, cp315t; **onnxruntime 1.31.1** `win_amd64` und `win_arm64` fuer cp311 bis cp314; **tokenizers 0.23.3** `cp310-abi3-win_amd64`. **av 19.0.2** verlangt Python >= 3.12 (Windows-Wheels `cp312-abi3`/`cp314-cp314t`); faster-whisper verlangt `av>=11` - fuer Python 3.11 muesste eine aeltere av-Version gewaehlt werden, ob es dafuer ein Windows-Wheel gibt, wurde **nicht** geprueft: offen. Gleiches gilt fuer **numpy 2.5.4** (`>=3.12`): fuer Python 3.11 waere eine aeltere Version noetig, nicht geprueft.
- **CPU ohne Grafikkarte:** > "Python 3.9 or greater"; GPU-Betrieb braucht cuBLAS/cuDNN, CPU nicht. Aufruf fuer CPU laut README: `WhisperModel(model_size, device="cpu", compute_type="int8")` (Fundstelle: faster-whisper README). Damit ist CPU-Betrieb ohne GPU **offiziell vorgesehen**.
- **whisper.cpp:** README: > "Support for CPU-only inference", Windows laut Plattformliste "Windows (MSVC and MinGW)"; Quantisierung (q5/q8) und optional Vulkan/OpenBLAS. Ob die Version v1.9.5 **fertige Windows-Binaerdateien** anbietet, ist **nicht belegt**: die Release-Seite zeigt nur "Assets 2", die Namen kamen im Abruf nicht an. Ohne fertige Binaerdatei muesste der Besitzer selbst bauen (MSVC): offen.
- **Vosk 0.3.45:** Wheel `py3-none-win_amd64` vorhanden (13 997 596 Byte), `requires_python >=3`. Sicher unter Windows installierbar, aber die Bibliothek ist stehen geblieben (letzte Veroeffentlichung 2022).
- **Silero-VAD:** `silero-vad` auf PyPI verlangt **`torch>=1.12.0`** (Pflicht), also eine mehrere hundert MB grosse Abhaengigkeit; die `onnx-cpu`-Extra bietet `onnxruntime`+`numpy`. **Wichtig:** faster-whisper bringt das Silero-Modell (`silero_vad_v6.onnx`) selbst mit und nutzt es ueber `onnxruntime` (`faster_whisper/vad.py`, Zeile 332: `os.path.join(get_assets_path(), "silero_vad_v6.onnx")`); die README des Projekts sagt, die Bibliothek "integrates the Silero VAD model". Eine eigene Installation von `silero-vad` (mit torch) ist dann **nicht** noetig.
- **Deutsch-Qualitaet** (keine eigene Messung, nur veroeffentlichte Zahlen):
  - **Whisper:** Die Whisper-Veroeffentlichung (https://arxiv.org/abs/2212.04356, Tabelle 13, WER auf Fleurs) nennt fuer die Modellgroessen tiny/base/small/medium/large/large-v2 in der ersten Spalte der Tabelle die Werte 27,8 / 17,9 / 10,2 / 6,5 / 5,5 / 4,5 Prozent. **Die Zuordnung dieser Spalte zur Sprache Deutsch ist aus dem maschinell ausgelesenen PDF nicht eindeutig belegt** (Spaltenueberschriften sind vertauscht ausgegeben); die Zahlen sind daher nur ein **Hinweis**, kein Beleg. Die README von `openai/whisper` verweist fuer Sprachen auf eine Abbildung und die Anhaenge D.1 bis D.4.
  - **Vosk:** offizielle Tabelle (WER in Prozent, https://alphacephei.com/vosk/models): `vosk-model-de-0.21` **9,83** (Tuda-de test), 12,82 (cv-test), 12,42 (mls), 24,00 (Podcast), 33,26 (mtedx); `vosk-model-small-de-0.15` **13,75** (Tuda-de test), 30,67 (Podcast). Das grosse Modell ist laut Tabelle fuer "telephony and server" gedacht.
  - Ein direkter Vergleich Whisper gegen Vosk ist aus diesen Quellen **nicht** moeglich (verschiedene Testdaten). Ein Vergleichsmessung auf deutschen JARVIS-Beispielsaetzen ist ein Vorschlag fuer einen Folgeschritt, kein Ergebnis dieser Pruefung.
- **Latenz auf einem normalen Windows-PC: nicht gemessen und nicht belegt.** Einzige offizielle Zahl: README von faster-whisper, Modell `small` auf CPU, 13 Minuten Audio, 8 Threads auf einem Intel Core i7-12700K (Beam 5): faster-whisper int8 **1 min 42 s** (RAM 1477 MB), fp32 2 min 37 s (2257 MB); whisper.cpp fp32 2 min 05 s (1049 MB); openai/whisper fp32 6 min 58 s. Das entspricht grob dem 0,13-fachen der Audiodauer (ein Mittelklasse-Desktop-Prozessor von 2021). Fuer einen schwaecheren Laptop sind das **keine** belegten Werte. Fuer die Sprachsteuerung zaehlt die Zeit pro kurzer Aeusserung (wenige Sekunden); sie wurde nicht erhoben: offen.
- **Modellgroessen** (Auswahl, aus den Hugging-Face-Metadaten, siehe "Pinning"): tiny 72 MiB, base 139 MiB, small 461 MiB, medium 1,42 GiB, large-v3 2,88 GiB; whisper.cpp quantisiert: small-q5_1 181 MiB, medium-q5_0 514 MiB, large-v3-turbo-q5_0 547 MiB. Vosk: `small-de-0.15` 44,3 MiB, `de-0.21` 1,9 GiB entpackt noch deutlich groesser (Zip 2 031 717 803 Byte).

## Transitive Abhaengigkeiten
Stand PyPI-Metadaten 2026-11-03 (nur Laufzeit-Abhaengigkeiten, keine Extras `dev`/`conversion`). Die Lizenz stammt aus den PyPI-Feldern/Klassifikatoren, nicht aus den LICENSE-Dateien der Pakete (die wurden **nicht** einzeln gelesen).

**faster-whisper 1.2.1** verlangt: `ctranslate2>=4.0,<5` (MIT), `huggingface-hub>=0.21` (Apache-2.0), `tokenizers>=0.13,<1` (Apache-2.0), `onnxruntime>=1.14,<2` (MIT), `av>=11` (BSD-3-Clause), `tqdm` (MPL-2.0 AND MIT).

| Paket | gepruefte Version | Lizenz laut PyPI | weitere Abhaengigkeiten |
|---|---|---|---|
| ctranslate2 | 4.8.5 | MIT | `numpy`, `pyyaml>=5.3,<7` (MIT) |
| onnxruntime | 1.31.1 | MIT License | `flatbuffers` (Apache 2.0), `numpy>=1.21.6`, `packaging` (Apache-2.0 OR BSD-2-Clause), `protobuf>=4.25.8` (3-Clause BSD) |
| av (PyAV) | 19.0.2 | BSD-3-Clause (PyPI `license_expression`), **Wheels buendeln FFmpeg** | keine |
| tokenizers | 0.23.3 | Apache (Klassifikator) | `huggingface-hub` |
| huggingface-hub | 2.4.0 | Apache-2.0 | `click` (BSD-3-Clause), `filelock` (MIT), `fsspec` (BSD-3-Clause), `hf-xet` (Apache-2.0, nativ), `httpx2` (BSD-3-Clause), `packaging`, `pyyaml`, `tqdm`, `typing-extensions` (PSF-2.0) |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | - |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | - |

- Die **PyAV-Wheels enthalten FFmpeg-Bibliotheken** ("Binary wheels ... with FFmpeg bundled", Fundstelle: https://raw.githubusercontent.com/PyAV-Org/PyAV/main/README.md). FFmpeg ist je nach Bauart **LGPL oder GPL**. Welche Bauart die PyPI-Wheels haben, wurde in dieser Pruefung **nicht** belegt: **offen und fuer die AGPL/GPL-Regel erheblich** (siehe unten). Hinweis: JARVIS braeuchte `av` nur zum Dekodieren von Audiodateien; Mikrofondaten kaemen als numpy-Feld.
- `tqdm` steht unter MPL-2.0 AND MIT: schwaches Copyleft (nur Dateiebene), laut `INTEGRATIONS.md` nur nach **ausdruecklicher Freigabe des Besitzers** zulaessig. **Frage an den Besitzer.**
- Die Metadaten von `av` und `numpy` auf PyPI haben im Feld `requires_dist` den Wert `None`; deren Abhaengigkeiten sind damit "keine" laut Register.
- **whisper.cpp (getrennter Prozess):** keine Python-Abhaengigkeit fuer JARVIS; Abhaengigkeiten des Programms wurden nicht erhoben (offen).
- **Vosk 0.3.45** verlangt: `cffi>=1.0`, `requests`, `tqdm` (MPL-2.0 AND MIT), `srt`, `websockets`. Lizenzen von `cffi`, `requests`, `srt`, `websockets` wurden **nicht** gelesen: offen. `requests` ruft beim Modell-Download das Netz.
- **silero-vad 6.2.3** verlangt `packaging` und **`torch>=1.12.0`**; torch ist laut PyPI (2.15.0) "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib", sehr gross; Extras `onnx-cpu`: `numpy`, `onnxruntime`.

## Sicherheitshinweise
- **Advisories:** keine veroeffentlichten Advisories fuer faster-whisper und whisper.cpp (siehe Pflege). CVE-Datenbanken wurden **nicht** durchsucht (keine offizielle Projektquelle): offen.
- **Native Binaerteile:** CTranslate2, onnxruntime, tokenizers, hf-xet, av (FFmpeg) und Vosk (Kaldi, `cffi`) liefern vorkompilierten Maschinencode aus PyPI-Wheels. Herkunft: die jeweiligen Projekte; Pinning mit Hash (siehe unten) bindet an die gepruefte Datei, ersetzt aber keine Quellpruefung.
- **Modelldateien sind Daten, kein Code:** Die Systran-Modelle bestehen aus `model.bin`, `config.json`, `tokenizer.json`, Vokabular. `openai/whisper-small` liegt zusaetzlich als `pytorch_model.bin` (Pickle-Format, kann beim Laden Code ausfuehren) und als `model.safetensors` vor. **Es gilt: nur `model.bin`/`.safetensors`/ggml-Dateien aus den genannten Repositories verwenden, nie Pickle-`.bin` aus unbekannter Quelle.**
- **Import/Installation:** Fuer die gepruefte faster-whisper-Wheel gibt es keine Installationsskripte (reine Wheel). Code beim Import / Nachladen: faster-whisper laedt beim ersten `WhisperModel("small")` das Modell aus dem Netz (siehe Datenabfluss).
- **Rechte:** Zugriff auf Mikrofon (gibt es bereits ueber `sounddevice`, `voice`-Extra) und Schreibzugriff auf einen Modellordner. Kein Administrator, keine Netzwerk-Server noetig.
- **Einbindung in JARVIS** (nur Hinweis fuer den spaeteren Schritt): STT erzeugt Text; die Ausfuehrung von Aktionen laeuft weiter ueber `ToolRegistry.execute` -> `PermissionEngine`. STT darf **keine** eigene Berechtigung erhalten; Verdrahtung nur in `src/jarvis/bootstrap.py`; Standard `enabled = false`.

## Datenabfluss
- **faster-whisper:** Im Betrieb laeuft die Erkennung lokal; Audio verlaesst den Rechner nicht. **Netzwerk:** laedt man ein Modell ueber seinen Namen (`WhisperModel("small")`), wird es laut README "automatically downloaded from the Hugging Face Hub" (Repository `Systran/faster-whisper-small`; Abbildung der Namen in `faster_whisper/utils.py`). Zusaetzlich kann `huggingface-hub` Anfragen (Metadaten, Version) senden. Ob und wie sich das ausschalten laesst (Umgebungsvariablen von huggingface-hub, `local_files_only`), wurde **nicht** an der offiziellen Dokumentation belegt: **offen, Ablehnungsgrund, solange nicht geklaert**. Entschaerfung fuer den spaeteren Einbau (Vorschlag): Modell vorab von Hand ablegen und nur aus lokalem Ordner laden, Netz im Prozess sperren.
- **whisper.cpp:** das Programm selbst ruft laut Dokumentation kein Netz auf (nicht ausdruecklich belegt: **offen**); Modelle werden ueber `models/download-ggml-model.cmd` bzw. `.sh` von Hugging Face geladen (https://huggingface.co/ggerganov/whisper.cpp). Die Datei kann der Besitzer auch von Hand holen.
- **Vosk:** Die Python-Bibliothek ruft ueber `requests` (Zeitlimit 10 s) die Modellliste `https://alphacephei.com/vosk/models/model-list.json` und laedt Modelle von `https://alphacephei.com/vosk/models/` (Fundstelle: `python/vosk/__init__.py`, Zeilen 17, 40 bis 114), **wenn** man `Model(lang=...)` oder `model_name` benutzt; mit einem lokalen Ordner (`model_path`) entfaellt das. Telemetrie: in den gelesenen Quellen nicht gefunden, aber auch nicht ausdruecklich ausgeschlossen.
- **Silero-VAD:** README: > "no telemetry, no keys, no registration, no built-in expiration, no keys or vendor lock." Das Modell liegt im Paket; kein Download noetig. Der Python-Hilfsaufruf `torch.hub.load` laedt dagegen aus dem Netz (nicht Teil der Empfehlung).
- **Speicherorte:** Hugging-Face-Zwischenspeicher im Nutzerordner (Standard unter `%USERPROFILE%\.cache\huggingface`, nicht aus der offiziellen Doku belegt: offen); Modelle koennen in einen frei waehlbaren Ordner gelegt werden. Aufnahmen speichert die Bibliothek nicht.
- **Keine nicht abschaltbare Telemetrie** wurde gefunden - dies ist aber **keine Bestaetigung** fuer huggingface-hub (siehe oben).

## Pinning mit Hash
Hashes stammen aus der Pruefung (PyPI-JSON, Hugging-Face-API, Vosk-Modellliste), nicht aus einer eigenen Berechnung; es wurde nichts heruntergeladen und verglichen. Windows 64 Bit, Python 3.11:

```
faster-whisper==1.2.1 --hash=sha256:79a66ad50688c0b794dd501dc340a736992a6342f7f95e5811be60b5224a26a7   (py3-none-any, 1 118 909 Byte)
ctranslate2==4.8.5   --hash=sha256:cb918ee10fd228c2aa2a5fde3e62999a4617cb11dae51644d5286a1b6d6783dd   (cp311-win_amd64, 20 405 543 Byte)
onnxruntime==1.31.1  --hash=sha256:c3d91b5de31e2fc82d71bd65b2b22bddee8b49057a3a36338e9a868e0ea90c05   (cp311-win_amd64, 14 885 761 Byte)
tokenizers==0.23.3   --hash=sha256:1f0823bb00c5fdc98e487354d54dd55a03848d61a1a0bf29a68c77f24f3b26c3   (cp310-abi3-win_amd64, 2 872 101 Byte)
huggingface-hub==2.4.0 --hash=sha256:42ecfd93ede47bdd333daebbf66a32d7bfe2e18752754fe4d2d4f98a0179d801 (py3-none-any, 857 021 Byte)
av==19.0.2           --hash=sha256:3ce5a1d7b916d13c16ac58f1756f0fee4af2d53f02bc1403e18550b50d375a22   (cp312-abi3-win_amd64; fuer Python 3.11 andere Version noetig, nicht gepruft)
vosk==0.3.45         --hash=sha256:6994ddc68556c7e5730c3b6f6bad13320e3519b13ce3ed2aa25a86724e7c10ac   (py3-none-win_amd64, 13 997 596 Byte)
silero-vad==6.2.3    --hash=sha256:7b7f5436cfcb02fae583a05b512ea96467fd449fe54cb49a5e4f06c51a1e43b8   (py3-none-any, 11 317 527 Byte)
```

Unvollstaendig bleiben die Hashes von `numpy`, `pyyaml`, `flatbuffers`, `protobuf`, `packaging`, `tqdm`, `click`, `filelock`, `fsspec`, `hf-xet`, `httpx2`, `typing-extensions` und von FFmpeg-bezogenen Teilen; sie sind vor einem Einbau im Schritt mit `pip install --require-hashes` (alle Artefakte) zu erheben. Die Wheel-Hashes fuer `numpy 2.5.4` (cp312) stehen in den PyPI-Daten, passen aber nicht zu Python 3.11.

**Modelle (SHA-256 laut Hugging-Face-LFS-Metadaten, Repository-Stand 2026-11-03; Revisionen in Klammern):**

| Modell | Datei | Groesse (Byte) | SHA-256 |
|---|---|---|---|
| Systran/faster-whisper-tiny (`d90ca5fe260221311c53c58e660288d3deb8d356`) | model.bin | 75 538 270 | `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1` |
| Systran/faster-whisper-base (`ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`) | model.bin | 145 217 532 | `d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9` |
| Systran/faster-whisper-small (`536b0662742c02347bc0e980a01041f333bce120`) | model.bin | 483 546 902 | `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` |
| Systran/faster-whisper-medium (`08e178d48790749d25932bbc082711ddcfdfbc4f`) | model.bin | 1 527 906 378 | `9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae` |
| Systran/faster-whisper-large-v3 (`edaa852ec7e145841d8ffdb056a99866b5f0a478`) | model.bin | 3 087 284 237 | `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1` |
| Systran/faster-distil-whisper-large-v3 (`c3058b475261292e64a0412df1d2681c06260fab`) | model.bin | 1 512 927 867 | `b79368e19b6623813609431a6e5ee309a71506701ebc49fd7820e692dec7c5f5` |
| ggerganov/whisper.cpp (`5359861c739e955e79d9a303bcbc70fb988958b1`) | ggml-small.bin | 487 601 967 | `1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b` |
| ggerganov/whisper.cpp | ggml-small-q5_1.bin | 190 085 487 | `ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb` |
| ggerganov/whisper.cpp | ggml-medium-q5_0.bin | 539 212 467 | `19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f` |
| ggerganov/whisper.cpp | ggml-large-v3-turbo-q5_0.bin | 574 041 195 | `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2` |
| ggerganov/whisper.cpp | ggml-large-v3.bin | 3 095 033 483 | `64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2` |
| Vosk `vosk-model-small-de-0.15` | Zip | 46 499 967 | **nur MD5** `4f21f92c0897b48287ef8839420608eb` (offizielle Modellliste; kein SHA-256 veroeffentlicht) |
| Vosk `vosk-model-de-0.21` | Zip | 2 031 717 803 | **nur MD5** `23298ddeb602739016956144ac4c74de` (offizielle Modellliste) |
| Silero-VAD `silero_vad.onnx` | im Paket | 2 327 524 | kein eigener Hash veroeffentlicht; bindet nur ueber den Wheel-Hash oben (`silero_vad-6.2.3`) |

Die whisper.cpp-README (`models/README.md`) fuehrt dazu eine "SHA"-Spalte mit 40 Hexzeichen (zum Beispiel `small`: `55356645c2b361a969dfd0ef2c5a50d530afd8d5`); das Verfahren (vermutlich SHA-1) nennt die Seite nicht. MD5 und SHA-1 gelten als schwach; fuer Vosk bleibt daher **keine** kryptografisch starke Pruefsumme: ein weiterer Grund gegen Vosk.

## Lizenzausschluss (AGPL/GPL)
- Code von faster-whisper, CTranslate2, whisper.cpp, Vosk, Silero-VAD und der Modelle (Whisper-Gewichte, Systran-Umwandlungen, ggml, Vosk-Apache-Modelle, Silero-Modell): **kein AGPL, kein GPL** festgestellt (MIT bzw. Apache-2.0).
- **Ausgeschlossen bleiben**: Vosk-Modell `vosk-model-small-de-zamia-0.3` (LGPL-3.0) und Vosk-Modelle mit AGPL (Tabelle fuehrt eines fuer Franzoesisch). Sie werden nicht empfohlen.
- **Transitive Abhaengigkeiten:** Fuer die Pakete der Tabelle oben ergab sich nach PyPI-Feldern kein AGPL/GPL. **Unbelegt ist die FFmpeg-Bauart in den av-Wheels** (kann LGPL oder GPL sein); eine abschliessende Feststellung "kein GPL" ist deshalb **fuer faster-whisper derzeit nicht moeglich**. Vorschlag zur Entschaerfung ohne Rueckfrage an das Projekt: `av` nicht zwingend noetig, wenn nur Mikrofon-Arrays dekodiert werden; ein Einbau muss aber `av` weiterhin installieren, solange faster-whisper es als Pflicht deklariert.
- **Regel zur getrennten Ausfuehrung:** Falls je ein GPL/AGPL-Teil noetig waere, duerfte er nur als **eigener Prozess ohne Einbindung** laufen (keine Bibliothek in JARVIS, Kommunikation ueber Standardein-/ausgabe oder lokalen Socket, Quelltext nicht verbunden), weil der Copyleft-Zwang nur fuer das gemeinsame Programmwerk gilt, nicht fuer Daten, die ueber eine Prozessgrenze fliessen. Das ist **keine Rechtsberatung** und hier **nicht** der Fall: Keiner der empfohlenen oder abgelehnten Kandidaten verlangt diese Ausnahme (whisper.cpp ist MIT; der Prozess-Betrieb waere eine Wahl wegen der Isolation, nicht wegen der Lizenz).

## Entscheidung
nehmen
Besitzer-Freigabe: 2026-11-03
**Entscheidung des Besitzers vom 2026-11-03 (im Projektchat ausdruecklich bestaetigt):** faster-whisper mit integriertem Silero-VAD wird als optionale lokale STT-Technologie fuer JARVIS genehmigt. Der Besitzer akzeptiert die in diesem Bericht dokumentierten offenen Lizenz- und Kompatibilitaetsfragen und autorisiert Dokumentation und Implementierung. Dies ist eine bewusste Risikoakzeptanz und **kein** Nachweis, dass die offenen Punkte inzwischen technisch oder rechtlich geklaert sind. Vor Nutzung auf Windows sind Abhaengigkeiten, Lizenzhinweise und Laufzeitverhalten zu pruefen.

**Verbindliche Implementierungsbedingungen:** Kein automatischer Modell-Download oder Netzwerkzugriff zur Laufzeit; Modell nur aus lokal konfiguriertem Pfad; standardmaessig deaktiviert; optionale Abhaengigkeit mit Lazy-Import; bestehende PermissionEngine, Not-Aus und Sitzungsbudgets bleiben wirksam. Windows-Echtmodelltest bleibt gesondert erforderlich. Die im Backlog verlangte formale Zeile `Besitzer-Freigabe: <Datum>` wird hier bewusst **nicht** durch den Assistenten gesetzt: laut Auftragsvertrag muss der Besitzer sie selbst per PR ergaenzen.

**Urspruenglicher Pruefbefund:** Bei jedem Kandidaten war mindestens ein Pflichtfeld offen (Datenabfluss/Telemetrie von huggingface-hub; FFmpeg-Lizenz in `av`; MPL-2.0 bei `tqdm`; Windows-Binaerdateien fuer whisper.cpp; Hashes aller Abhaengigkeiten; Python-3.11-Wheels fuer `av`/`numpy`). Die obige Besitzerentscheidung akzeptiert diese Unsicherheiten fuer die weitere Entwicklung, ohne sie als geklaert darzustellen.

**Ausdrueckliche Empfehlung je Kandidat:**
1. **faster-whisper (mit CTranslate2) mit dem mitgelieferten Silero-VAD (ONNX)** - **Empfehlung: Alternative / erste Wahl nach Klaerung der offenen Fragen.** Gruende: MIT bei Code **und** Modellen mit Modellkarte und SHA-256; CPU-Betrieb mit `int8` ohne Grafikkarte offiziell vorgesehen; Windows-Wheels fuer ctranslate2/onnxruntime fuer Python 3.11 belegt; aktive Pflege von CTranslate2; Whisper deutlich besser fuer beliebige deutsche Sprache als Vosk (Hinweis, kein Vergleichsbeleg). Das Modell `small` (461 MiB, int8) ist der konservative Startwert; `medium` oder `large-v3-turbo` nur nach Messung der Latenz auf dem Zielrechner.
2. **whisper.cpp als getrennter Prozess** - **Alternative, zweite Wahl.** MIT, kleine Quantisierungen (`small-q5_1` 181 MiB), keine Python-Abhaengigkeiten fuer JARVIS und saubere Prozessgrenze. Gegen: Windows-Binaerdatei der Version v1.9.5 nicht belegt; Aufruf als Unterprozess braeuchte eine eigene Pruefung durch `PermissionEngine`.
3. **Vosk - nicht nehmen.** Apache-2.0, kleine Modelle (44,3 MiB), aber: letzte PyPI-Version 2022-12, deutsche Modelle von 2020/2021, nur MD5 als Pruefsumme, schlechtere veroeffentlichte WER (13,75 % gegen 9,83 % fuer das grosse Modell, Tuda-de), Model-Download ueber `requests`.
4. **Silero-VAD als eigenes Paket (`silero-vad` mit torch) - nicht nehmen.** Das Modell ja (MIT, 2,3 MB), aber ueber den mit faster-whisper gebuendelten ONNX-Pfad; die zusaetzliche torch-Abhaengigkeit ist unnoetig gross.

**Offene Fragen fuer den Besitzer (Antworten noetig vor einem Einbauschritt):**
1. Freigabe fuer `tqdm` (MPL-2.0 AND MIT) als schwaches Copyleft, weil faster-whisper es verlangt?
2. Bestaetigung, dass die PyAV-Wheels (mit gebuendeltem FFmpeg) unter LGPL-Bedingungen akzeptabel sind; sonst `faster-whisper` nicht nehmen. Eine Folgepruefung muss die Bauart von FFmpeg in den av-Wheels belegen.
3. Soll der Netzabfluss beim Modellladen (huggingface.co) akzeptiert werden, oder muss das Modell per Hand abgelegt und der Zugriff erzwungen offline sein (empfohlen)? Eine Folgepruefung muss die offizielle huggingface-hub-Dokumentation zu Telemetrie und `local_files_only` belegen.
4. Welche Zielhardware gilt (CPU-Modell, Kerne, RAM)? Fuer eine belegte Latenzaussage braeuchte es einen Windows-Messlauf mit einem deutschen Satzkorpus (CI-Windows oder Rechner des Besitzers), den dieser Bericht nicht liefert.
5. Welche Python-Version laeuft auf dem Zielsystem (3.11 oder 3.12+)? Davon haengen `av`/`numpy`-Wheels ab.
6. Welche Modellgroesse ist akzeptabel (Speicher, Wartezeit): `small` int8, `medium`, `large-v3-turbo`?
7. Whisper-Gewichte werden in den Quellen teils unter MIT, teils unter Apache-2.0 gefuehrt; beide sind zulaessig. Reicht diese Feststellung, und ist die offene Lizenz der Trainingsdaten fuer den privaten Einsatz hinnehmbar?
8. Die README von Silero-VAD zeigt ein Abzeichen mit "CC BY-NC 4.0" im Alt-Text, der LICENSE-Text ist MIT. Genuegt MIT als massgeblich (wie hier angenommen)?

## Pruefung (Datum und Quelle)
2026-11-03. Quellen (alle offiziell, abgerufen am selben Tag):
- faster-whisper: https://github.com/SYSTRAN/faster-whisper (README, `LICENSE`, `faster_whisper/utils.py`, `faster_whisper/vad.py`, Advisories-Seite), https://pypi.org/pypi/faster-whisper/json
- CTranslate2: https://raw.githubusercontent.com/OpenNMT/CTranslate2/master/LICENSE, https://pypi.org/pypi/ctranslate2/json
- whisper.cpp: https://github.com/ggml-org/whisper.cpp (README, `LICENSE`, `models/README.md`, `models/download-ggml-model.cmd`, Releases-Seite v1.9.5, Advisories-Seite)
- Vosk: https://github.com/alphacep/vosk-api (`COPYING`, `python/vosk/__init__.py`), https://pypi.org/pypi/vosk/json, https://alphacephei.com/vosk/models, https://alphacephei.com/vosk/models/model-list.json (HTTP-Kopfzeilen der Modell-Zips)
- Silero-VAD: https://github.com/snakers4/silero-vad (README, `LICENSE`), https://pypi.org/pypi/silero-vad/json
- Whisper (Modelle): https://github.com/openai/whisper (README, `LICENSE`), https://arxiv.org/abs/2212.04356 (Tabelle 13), https://huggingface.co/api/models/Systran/faster-whisper-{tiny,base,small,medium,large-v3}, https://huggingface.co/api/models/Systran/faster-distil-whisper-large-v3, https://huggingface.co/api/models/ggerganov/whisper.cpp, https://huggingface.co/api/models/openai/whisper-small
- Abhaengigkeiten: PyPI-JSON der Pakete `onnxruntime`, `av`, `tokenizers`, `huggingface-hub`, `numpy`, `tqdm`, `flatbuffers`, `protobuf`, `packaging`, `pyyaml`, `click`, `filelock`, `fsspec`, `hf-xet`, `httpx2`, `typing-extensions`, `torch`; https://raw.githubusercontent.com/PyAV-Org/PyAV/main/README.md
- Nicht erreichbar bzw. nicht verwertbar: GitHub-API (`api.github.com`, HTTP 403 im Sitzungsproxy), die Dateinamen der Release-Anhaenge von whisper.cpp, `SECURITY.md` von whisper.cpp, GitHub-Advisories von CTranslate2/Vosk/Silero-VAD. Die uebrigen Angaben wurden erreicht; Luecken sind oben als "offen" gekennzeichnet.
