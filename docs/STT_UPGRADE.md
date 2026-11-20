# Speech Recognition Upgrade V1 (Stand 2026-11-15)

Status: **Code, Konfiguration, Tests und Modellvergleich (CPU/int8, synthetischer Korpus) fertig.** Standard `whisper-base`, `whisper-medium` als Qualitätsoption (Owner-Vorgabe), **vorläufig** (keine echten Aufnahmen).

## 1. Bestandsaufnahme
**Audiopfad:** Mikrofon (`sounddevice`, 16 kHz mono) -> `SoundDeviceSource.record` (Endpointing: Pegel oder VAD, meldet den Pegel an NEXUS) -> `AudioClip` -> `STTProvider.transcribe` -> `SpeechListener` (Nachbearbeitung) -> `VoiceSession.process` -> `JarvisCore.handle` -> TTS. Bis jetzt: Provider `local` = faster-whisper mit einem Modellordner (`voice.stt_model_dir`, **kein Download**, `C:/JARVIS-Test/models/whisper-base`, 142 MB), `openai` mit `whisper-1`.
**Hardware (gemessen):** Intel i5-9600KF (6 Kerne, 6 Threads), 7,9 GB RAM (zum Messzeitpunkt 1,7 GB frei), NVIDIA GTX 1060 **3 GB** (Pascal, ca. 2,2 GB frei), 519 GB frei auf C:. ctranslate2 4.9.0 meldet 1 CUDA-Gerät, aber `cublas64_12.dll` fehlt: **GPU-Betrieb ist ohne zusätzliche CUDA-Bibliotheken nicht möglich** (nicht installiert, keine Freigabe). Damit läuft alles auf der CPU (`int8`).

## 2. Modellkandidaten, Herkunft und Lizenzen (vor dem Download geprüft, Hugging Face API 2026-11-15)
| Modell | Repository | Format | Lizenz | Größe | Herkunft / Hinweis |
|---|---|---|---|---|---|
| base (vorhanden) | lokal | CTranslate2 | MIT | 142 MB | bisheriger Standard, bleibt Rückfallweg |
| small | `Systran/faster-whisper-small` | CTranslate2 | MIT (Tag `license:mit`) | 464 MB | Systran = Betreiber von faster-whisper, nicht gated |
| medium | `Systran/faster-whisper-medium` | CTranslate2 | MIT | 1,46 GB | wie oben |
| large-v3-turbo | `dropbox-dash/faster-whisper-large-v3-turbo` | CTranslate2 | MIT (Tag und Modellkarte) | 1,55 GB | Das ist der Repo, auf den faster-whisper selbst als Alias „turbo“ zeigt (`mobiuslabsgmbh/...`); Hugging Face leitet den alten Namen per Umbenennung dorthin weiter. 3,4 Mio. Downloads, nicht gated. Herkunftshinweis: die Organisation heißt jetzt anders als im Alias. |
| primeline `whisper-large-v3-turbo-german` | – | nicht CTranslate2 | uneinheitlich | – | **übersprungen** (Lizenz unklar, Konvertierung nötig) |
| Whisper large-v3 (voll) | – | – | MIT | ~3 GB | **nicht geplant** (RAM/Latenz) |
Geladen wurden nur `config.json`, `model.bin`, Tokenizer/Vokabular und README nach `C:\JARVIS-Test\models\whisper-{small,medium,large-v3-turbo}`. Modelle werden weiter nur lokal geladen (`local_files_only`).

## 3. Benchmark (reproduzierbar)
```powershell
.\.venv\Scripts\python.exe scripts\sttenchmark.py prepare
.\.venv\Scripts\python.exe scripts\sttenchmark.py run --model base=C:/JARVIS-Test/models/whisper-base --model small=C:/JARVIS-Test/models/whisper-small --device cpu --compute int8
# je Modell ein eigener Prozess; weitere Optionen: --language auto, --hints, --beam 1, --threads 6, --real
```
**Korpus:** 23 **synthetische** Dateien (Windows-Stimmen Hedda/Zira, ca. 200 Referenzwörter). Maschinenstimme = deutlich leichter als echte Sprache; echte Dialekte, Akzente und Umgangssprache sind **nicht gemessen**. Eigene Aufnahmen nach `data\stt-corpus
eal\` (`<name>.wav` + `<name>.txt`) und `--real`.
**Messung:** CPU `int8` (6 Kerne, Bibliotheksstandard für Threads), Beam 5, Sprache je Eintrag, ein Modell nach dem anderen (freier RAM vorher 1,6-2,5 GB). WER = gewichtet über alle Wörter (Mittel je Datei in Klammern, weil kurze Sätze dort überproportional zählen); „nach NB“ = nach der Nachbearbeitung der Eigennamen.
| Modell | Laden | warm (Median) | RTF | RAM-Spitze | WER | (je Datei) | WER nach NB | CER | kritische Wörter |
|---|---|---|---|---|---|---|---|---|---|
| base | 0,4 s | **0,87 s** | 0,24 | 420 MB | 14,4 % | 14,5 % | 14,4 % | 6,9 % | 34/44 |
| small | 2,0 s | 2,6 s | 0,63 | 701 MB | 15,8 % | 20,3 % | 15,8 % | 6,4 % | 34/44 |
| medium | 6,4 s | 7,6 s | 1,80 | 1,75 GB | 12,4 % | 16,0 % | **11,4 %** | 3,7 % | **39/44** |
| large-v3-turbo | 6,8 s | 10,7 s | 2,68 | 1,89 GB | **10,4 %** | 13,3 % | **9,4 %** | **3,1 %** | 37/44 |
Weitere Läufe (Beam 1, 6 Threads): small 2,4 s / WER 16,8 %, medium 6,7 s / 11,9 %, turbo 10,0 s / 9,4 %, base 0,81 s / 15,3 %. **Beam 1 spart kaum Zeit**, weil Whisper je Äußerung immer ein 30-s-Fenster verarbeitet: die Zeit ist fast unabhängig von der Länge der Aussage. GPU: nicht messbar (`cublas64_12.dll` fehlt, keine CUDA-Installation freigegeben). `language=auto` mit base war schlechter und langsamer (WER 19,5 %, 1,6 s).
**Aussagen, die die Zahlen tragen:** (1) small ist **kein** Gewinn gegenüber base (langsamer, WER/Kritische gleich oder schlechter, CER minimal besser). (2) medium und turbo sind klar genauer bei Umlauten, Technik und Namen (CER fast halbiert, JARVIS wird als „Javis“ statt „Schau“/„Herrischer Wiss“ gehört). (3) Beide sind auf dieser CPU langsam: medium ca. 7-8 s, turbo ca. 11 s je Äußerung; turbo ist für einen Sprachdialog nicht brauchbar und braucht ~1,9 GB RAM bei oft nur ~2 GB freiem Speicher. **Nicht belegt:** Verbesserungen für echten Dialekt/Akzent/Umgangssprache, Verhalten im Alltag mit Hintergrundgeräuschen. Der Korpus ist klein: Unterschiede von 1-2 Prozentpunkten WER sind Rauschen.
Befehls-Semantik: „Lies“ und „Lösche“ wurden von **allen** Modellen richtig erkannt (nie vertauscht). Dateinamen wie „bericht.txt“ zerfallen bei allen (TTS liest „Punkt“ mit): kritische Wörter sinken dadurch bei Befehlen, unabhängig vom Modell.

## 3a. Entscheidung (Owner-Vorgabe 2026-11-15, an die Messung gebunden)
* **Standard der Windows-Testkonfiguration: `whisper-base`** (schnell: ca. 0,9 s je Äußerung, 420 MB RAM). **`whisper-medium` bleibt als manuell wählbare Qualitätsoption** (Zeilen als Kommentar in `config\nexus.voice-test.toml`): deutlich genauer (CER 3,7 % statt 6,9 %, 39 statt 34 kritische Wörter, Namen erkannt), aber ca. 7-8 s je Äußerung und 1,75 GB RAM. **`large-v3-turbo` wird nicht Standard** (ca. 11 s, 1,9 GB RAM). small ist dominiert (kein Gewinn gegenüber base, langsamer).
* Die Standardwahl bleibt **vorläufig**: Verbesserungen für echten Dialekt/Akzent/Umgangssprache sind unbelegt; der Korpus ist klein und synthetisch.
* Wechsel auf medium: `stt_model_dir` auf `whisper-medium` und `stt_fallback_model_dir` auf `whisper-base` setzen; der Rückfall wird nur geladen, wenn das Hauptmodell fehlt oder scheitert (nie beide gleichzeitig im RAM).
* **Latenz-Optionen ohne Umbau geprüft (CPU int8, identischer Korpus):** `cpu_threads` 0/4/6: base 1,13 / 1,01 / 1,29 s, medium 7,5 / – / 7,1 s (Messrauschen, kein belastbarer Gewinn); Beam 1 statt 5: base 0,81 s statt 0,87 s, medium 6,7 s statt 7,6 s bei etwas schlechterer WER. Grund: Whisper verarbeitet je Äußerung immer ein 30-s-Fenster, die Zeit hängt kaum von der Satzlänge ab. **Keine dieser Einstellungen wird übernommen** (kein belastbarer Gewinn, Genauigkeitsverlust). Eine echte Beschleunigung bräuchte die GPU (CUDA-Bibliotheken fehlen) oder ein kleineres Modell.

## 4. Umsetzung
* `voice.stt_provider`: `local` (Hauptmodell, dann `voice.stt_fallback_model_dir`, nie Cloud), `auto` (wie `local`; Cloud **nur** mit `voice.stt_cloud_enabled = true` und Schlüssel), `openai` (ausdrücklich Cloud), `mock`, `console`. Standard bleibt `console`; `stt_cloud_enabled` ist standardmäßig **aus**.
* Kette `FallbackSTT` (`voice/stt_strategy.py`): Not-Aus/Budget wird vor **jedem** Provider geprüft und bricht ab, nie ein Ausweichen auf die Cloud (`STTHalted`); verständliche Sammelmeldung, wenn alle scheitern; Diagnose der letzten 5 Erkennungen (Originaltext, Provider, Dauer, kein Audio).
* OpenAI `gpt-transcribe` (`openai_provider.py`, Doku von developers.openai.com gelesen): Formularfelder `languages[]` (ersetzt `language`), `keywords[]` (nur einzeilig, ohne `<>`), `prompt`; ältere Modelle bekommen `language`/`prompt`. Standardmodell `gpt-transcribe` (`whisper-1`, `gpt-4o-*-transcribe` sind laut Doku veraltet, Abschaltung 26.02.2027). Fehler werden erklärt (Schlüssel, Limit, Netz, Zeitlimit), der Schlüssel erscheint nie in Meldungen. **Es wurde kein einziger echter Request gesendet.** Gegen die offizielle Doku (Guide und API-Referenz, 2026-11-15 gelesen) geprüft und korrigiert: `response_format` wird für `gpt-transcribe` nicht gesendet (Standard json; eine Einschränkung steht dort nicht), ungültige Sprachcodes werden vor dem Senden abgelehnt, Aufnahmen über 25 MB ebenfalls. Unbelegt in der Doku: Prompt-Längenlimit für `gpt-transcribe`, Preise (hier auf 500 Zeichen/30 Stichwörter begrenzt).
* Lokal: `voice.language = "auto"` (Spracherkennung durch das Modell, z. B. Mischsätze) und Stichworthinweise (`stt_keywords`, `stt_prompt` -> `initial_prompt`).
* Mikrofon: `voice.audio_device` ersetzt den fest kodierten Index 2: leer = Windows-Standardgerät (geprüft), Zahl = Index, sonst Namensteil; bei jeder Aufnahme neu aufgelöst; verständlicher Fehler mit Liste der Eingabegeräte. **Verhalten ändert sich für bestehende Konfigurationen:** wer ein bestimmtes Mikrofon nutzte, setzt `audio_device` auf dessen Namensteil (in `config\nexus.voice-test.toml` ergänzt).
* Nachbearbeitung (`voice/postprocess.py`): nur bekannte Fehlhörungen der Eigennamen (JARVIS, NEXUS) als ganze Wörter; sonst nichts erfunden. Riskante Sprachbefehle (löschen, bezahlen, herunterfahren ...) werden **nicht** ausgeführt, sondern zurückgefragt („Bestätige …“). Das ersetzt keine Freigabe: jede Aktion läuft weiter über PermissionEngine/Dialog.
* NEXUS: die Einrichtungsansicht zeigt jetzt, **wo** erkannt wird (lokal/Rückfall/Cloud, „kein Audio im Internet“) und welches Mikrofon. **Bewusst nur lesend:** Provider/Modell ändern bleibt in der Konfiguration, weil ein Schalter im Dashboard, der Audio in die Cloud freigibt, ein neuer Schreibweg mit Sicherheitsfolgen wäre (Owner-Entscheidung).

## 5. Konfiguration (Beispiel, nur lokal)
```toml
[voice]
stt_provider = "local"                          # local | auto | openai
stt_model_dir = "C:/JARVIS-Test/models/whisper-small"          # nach dem Vergleich: das beste Modell
stt_fallback_model_dir = "C:/JARVIS-Test/models/whisper-base"  # bleibt der Rückfallweg
language = "de"                                 # "auto" für deutsch-englische Mischsätze (langsamer, siehe Messung)
audio_device = ""                              # leer = Windows-Standardgerät; sonst Index oder Namensteil des Mikrofons
# Cloud nur bewusst (kostet Geld, Audio verlässt den PC): stt_provider = "auto", stt_cloud_enabled = true, Umgebungsvariable OPENAI_API_KEY
```

## 6. Offen / nächste Schritte
1. S2-Handmessung (Zeit bis Text, 5x) mit dem Standardmodell base.
2. Echte Aufnahmen (Umlaute, Dialekt, Akzent, Mischsprache) vom Owner für `--real`; bis dahin sind Verbesserungen für diese Fälle **unbestätigt**.
3. Optional GPU: CUDA-12-Bibliotheken (cuBLAS/cuDNN) wären nötig; bei 3 GB VRAM nur kleine Modelle sinnvoll. Nicht empfohlen vor dem CPU-Vergleich.
4. Live-Test OpenAI nur nach eigener Freigabe (Kosten, Audio ins Internet).
