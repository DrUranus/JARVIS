# #186 – Owner-Paket (Stand 2026-11-18) und Manifest-Review

## 1. Offene Handtests in drei Blöcken
Reihenfolge sicher: erst NEXUS-Fenster, dann Sprache, zuletzt UAC. Keine Aktion bestätigt Claude für dich.

**Block A – NEXUS (Browser, ca. 5 Min.)**
1. B9-3d: Befehl `Erstelle die Datei b93d_retry.txt mit dem Inhalt: test`; bei offener Frage im Konsolenfenster von NEXUS Strg+C. Erwartet: Datei fehlt, Audit `confirmation_rejected`.
2. B9-4: NOTAUS in Dashboard, Orb und Overlay; danach Auftrag senden (muss verweigert werden); danach Aufheben/Reset und Auftrag (muss wieder gehen). Frage zum Reset: erwartetes Verhalten laut Matrix S8b.
3. S9: nach Abbruch `/resume` im neuen NEXUS: unterbrochenes Ziel wird angeboten, nichts läuft ohne neue Freigabe.

**Block B – Sprache (Mikrofon, ca. 5 Min.)**: S2a/b/c, S3a, S4, S8a laut `docs/ABNAHME_186_COMPUTERUSE_UND_HANDTESTS.md`.

**Block C – UAC (nur Owner)**: S6.

## 2. Manifest-Blocker (pr-tests, `test_protected_files`)
Ursache: Die vom Owner genehmigte Erweiterung des UI-Vertrags (`steps`, Commit 858eff0) änderte zwei geschützte Dateien:
- `src/jarvis/ui_contract/schema.py`: `ACTIVITY_ITEM` + optionales Feld `"steps": Num(0, 200)`.
- `src/jarvis/ui_contract/schema/ui-events.schema.json`: generiert, gleiche Ergänzung (`minimum 0`, `maximum 200`, `number`).
Nichts an Berechtigungen, X0 oder Not-Aus geändert. Das Feld ist optional (alte Clients unberührt).

Review-Schritte für den Owner:
1. `git diff 04fd87b 194562f -- src/jarvis/ui_contract` lesen (7 Zeilen).
2. Nur bei Zustimmung: `python -m tests.support.protected_manifest --write --confirm-owner-review`, danach `git diff tests/support/protected_manifest.json` (nur diese zwei Hashes dürfen sich ändern), Commit durch den Owner.
Stand lokaler Hashes (SHA-256, Anfang): schema.py 5ab317fccaa0b311, ui-events.schema.json 96feca3c14824cbf.
Claude hat das Manifest NICHT geändert.

## 3. CI-Stand (API, Abfrage 2026-11-18)
- 858eff0: tests success, GUI E2E success, uia-compat success, **pr-tests failure** (tests-linux und tests-windows beide failure; Linux belegt = Manifest, Windows-Grund nicht einzeln geprüft).
- 194562f: GUI E2E success (native-desktop, browser-e2e win/linux); pr-tests und uia-compat dafür nicht gestartet (Owner startet sie manuell). Windows-Nachweis für 194562f steht damit aus.

## 4. Restblock Sprache und UAC (Stand nach S9)
Voraussetzung: NEXUS mit Mikrofon-Konfiguration (`config/nexus.voice-test.toml`), nur eine Instanz.
1. **S2a/b/c:** Sprachmodus starten, 5 Sätze sprechen (Pegel bewegt sich, Satz erkannt; Zeiten notieren, Median). Mikrofon ziehen: verständliche Meldung; wieder anstecken: Sprache läuft.
2. **S3a:** befehlsähnlichen Satz sprechen („Lösche alle Dateien“): wird nur erkannt/gesprochen, nichts ausgeführt (keine Datei, Prozesse gleich).
3. **S4:** 5 Antworten hören: deutsche Stimme, Umlaute, Latenz hörbar akzeptabel (Werte notieren).
4. **S8a:** Antwort sprechen lassen und NOTAUS drücken: Stimme in höchstens 1 s weg.
5. **S6 (nur Owner):** UAC-Dialog selbst auslösen und selbst entscheiden; Ergebnis melden.
Claude simuliert kein Mikrofon und keine UAC-Eingabe.

## 5. Sprachtest-Umgebung (2026-11-18) und Korrektur der Testbezeichnungen
Instanz: `.venv\Scripts\python.exe`, `config/nexus.voice-test.toml` (unverändert, SHA-256 geprüft), Whisper-base lokal, Windows-TTS (Hedda de-DE), Mikrofon laut Konfiguration „Auna“ (Windows-Standard ist das Razer-Headset). Korrektur: **S3a = deutsche Stimme (Hörprobe, Umlaute)**, **S3b = befehlsähnlicher Text wird nur gesprochen, nicht ausgeführt** (die Zuordnung in Abschnitt 4 oben war vertauscht).
**S3b-Hinweis:** Es gibt keinen reinen „Nur-Transkription“-Modus. Ein gesprochener Satz läuft wie eingetippter Text durch den normalen Weg (Ziel -> Berechtigungs-Engine). Es gibt kein Lösch-Werkzeug; Dateierstellung fragt immer. Der sichere Test ist daher: harmloser befehlsähnlicher Satz, erwartet wird höchstens eine Freigabefrage, die abgelehnt wird; keine Datei, keine Ausführung.

## 6. F-S9-1 – minimaler Lösungsvorschlag (NICHT umgesetzt, braucht Freigabe)
Problem: `cli._resume.confirm` ruft `provider.confirm(...)` direkt auf; die Frage `resume_step` und die Antwort erscheinen nicht im Audit.
Vorschlag: im selben `confirm`-Closure nach der Entscheidung zwei Auditereignisse über das vorhandene `core.permissions.audit` schreiben (`confirmation_requested` vorher, `confirmation_accepted`/`confirmation_rejected` nachher; Werkzeug `jarvis`, Aktion `resume_step`, Ressource `journal`, ohne Ziel-Inhalt). Keine Änderung an Entscheidungslogik, PermissionEngine, X0 oder Notaus; Audit-Fehler = Frage gilt als abgelehnt (fail-closed). Tests zuerst: (1) Ablehnen schreibt requested+rejected, (2) allow_once schreibt requested+accepted, (3) Auditfehler = abgelehnt, (4) kein Schlüssel/Zieltext im Eintrag.

## 7. S2b-Befund (Owner-Lauf 2026-11-18) – Diagnose und begrenzte Reparatur
**Sprachpfad:** Mikrofon (`SoundDeviceSource`) -> faster-whisper (`stt_provider=local`) -> `normalize_transcript` (nur Eigennamen JARVIS/NEXUS) -> `VoiceSession` (Wake-Word-Filter) -> `core.handle` -> LLM-Provider -> Windows-TTS. Der erkannte Satz geht unverändert (außer dieser Namens-Normalisierung) an `core.handle`.

1. **Immer „Hallo, ich bin bereit“ – Ursache nachgewiesen:** `config/jarvis.toml` setzt `[llm] provider = "mock"`; `src/jarvis/llm/mock.py` liefert fest „Hallo. Ich bin bereit.“. Die Voice-Test-Konfiguration überschreibt `[llm]` nicht. Kein Fehler im Sprachpfad: es ist der Demo-LLM. Eine echte Antwort braucht einen echten Provider (`openai`/`anthropic` mit Schlüssel nur als Umgebungsvariable; `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` sind im Prozess NICHT gesetzt). **Nicht von Claude änderbar (Zugangsdaten/Provider = Owner-Entscheidung), Reparatur daher NICHT durchgeführt.** Auswirkung: S2b-Zeiten messen nur Aufnahme+Whisper+TTS (~3 s), keine LLM-Zeit; S4-Inhalte sind immer derselbe Satz (Latenz und Stimme sind trotzdem prüfbar); S8a funktioniert nur, wenn die Sprachausgabe lang genug ist (der Mock-Satz ist kurz: längere Ausgabe z. B. über einen langen Text nötig).
2. **Verzögertes „Sprache beenden“ – Ursache nachgewiesen und behoben:** `GuiController.stop_voice` setzte nur ein Flag, das `VoiceSession.run` zwischen den Äußerungen prüft; die blockierende Aufnahme (`SoundDeviceSource.record`) wartet ohne Sprache bis `voice.max_record_seconds` = 15 s (VAD-Weg: 5 s). Reparatur: `cancel()` auf `AudioSource`/`Listener` (Standard: nichts), `SoundDeviceSource` bricht Warten und Aufnahme sofort ab und verwirft sie (gibt `None` zurück), `VoiceSession.cancel_listening()`, `stop_voice` ruft es auf. Betrifft nur die Aufnahme; PermissionEngine, X0, Notaus, Freigaben unverändert. Eine bereits laufende Whisper-Erkennung/TTS-Ausgabe wird nicht unterbrochen (Rest-Verzögerung nur, wenn gerade transkribiert wird).
3. **Wake-Word „Jarvis“:** Vorhanden ist nur der **textbasierte** Filter (`voice.wake_word`, `voice.require_wake_word`, Standard aus): nach dem Start des Sprachmodus wird bei `require_wake_word = true` nur auf Sätze reagiert, die mit „Jarvis“ beginnen. Ein **Audio-Hotword-Detektor** (Dauer-Lauschen, Start ohne Klick) existiert nur als Mock (`hotword_detector = "mock"`), es gibt keinen echten Detektor; der Sprachmodus startet bewusst nur per Klick („Das Mikrofon ist jetzt aktiv“). Das ist keine neue Konfiguration, sondern **neue Architektur** und braucht vorab eine Freigabe.
**Optionen (Owner-Entscheidung):** (A) Provider: `llm.provider = "openai"`/`"anthropic"` mit Schlüssel als Umgebungsvariable, nur lokal, nicht im Repo. (B) `require_wake_word = true` in der Voice-Test-Konfiguration für den textbasierten Filter (kleine Konfig-Änderung, auf deine Freigabe). (C) Echter Audio-Wakeword-Detektor (z. B. offline openWakeWord/Porcupine-ähnlich) als eigener Schritt mit Sicherheitsprüfung: nur Ja/Nein-Signal, kein Netz, nie Freigabe (siehe `HotwordGatedSource`).
**V1-Abgleich:** ein Sprachmodus per Klick, lokale Spracherkennung, TTS Windows und Not-Aus entsprechen den Abnahmekriterien; „inhaltlich passende Antworten“ und „Aktivierungswort ohne Klick“ sind mit Mock-LLM bzw. ohne Detektor NICHT erfüllbar (daher offen, nicht als bestanden zu werten).
**Tests:** `tests/test_voice_stop_cancel.py` (6 neu: Abbruch Standard-/VAD-Weg unter 2,5 s und Rückgabe None, Weiterreichen über Hotword-Gate/Listener, `cancel_listening` tolerant, `stop_voice` ruft ab); bestehend grün: `test_voice*`, `test_session_budget`, `test_control_center_voice*`, `test_emergency_stop`, `test_gui_model`, `test_ui_event_bus`, `test_control_center_binding`.

## 8. Echter LLM-Provider für den Voice-Test (Vorbereitung, 2026-11-18; NICHT aktiviert)
**Befund:** Die Provider-Integration ist vorhanden und braucht keine Code-Änderung: `openai`, `anthropic` (reines HTTPS ohne SDK) und `openai_compatible` (nur Loopback, Fremd-URL nur mit `allow_remote`). Der Schlüssel kommt nur aus der Umgebung (`OPENAI_API_KEY` bzw. `ANTHROPIC_API_KEY`; in einer Datei ist er für `openai_compatible` verboten); `LLMSettings.api_key` hat `repr=False` (im Test nicht in `repr`). Der Anbieter/das Modell werden per `JARVIS_LLM_PROVIDER` / `JARVIS_LLM_MODEL` gesetzt, ohne Datei. **Gefundener Fehler, behoben (Test zuerst):** Wiederholt der Anbieter den Schlüssel in einer Fehlerantwort, stand er im `LLMError`-Text (belegt mit gefälschtem Schlüssel, offline). Jetzt wird er durch `***` ersetzt, ohne Verkettung (`tests/test_llm_key_scrub.py`, 4 Tests; `test_llm*` grün). Echte OpenAI-Antworten maskieren den Schlüssel selbst; das ist eine zusätzliche Absicherung.
**Kostenbegrenzung (vorhanden, Standard AUS):** `[llm_budget]` / `JARVIS_LLM_BUDGET_ENABLED=true`: Aufrufe je Sitzung (Standard 30), Tokens je Aufruf und je Sitzung (Standard 100 000 gesamt), optional `max_cost` mit Preistabelle (nur in der TOML, `prices = ["modell;input_je_1k;output_je_1k"]`; über Umgebungsvariable nicht möglich, da `;` Listentrenner ist). Ohne bekannten Preis lehnt ein Kostenlimit fail-closed ab. Not-Aus blockiert LLM-Aufrufe. Fehlerbehandlung: HTTP-/Netzfehler -> `LLMError` mit gekürztem Text (kein Retry, kein Ausweichen auf ein anderes Modell).
**Datenschutz:** Mit echtem Provider verlässt der erkannte Satz (und der Gesprächsverlauf) den PC Richtung Anbieter. Whisper bleibt lokal. Nichts davon wurde ausgeführt.
**Einrichtung (in DEINEM PowerShell-Fenster; Claude fasst den Schlüssel nicht an):**
```powershell
cd C:\JARVIS-Test\V2
$env:JARVIS_LLM_PROVIDER = "openai"                       # oder "anthropic"
$env:JARVIS_LLM_MODEL    = "<Modell laut deinem Konto, klein und günstig>"
$env:JARVIS_LLM_MAX_TOKENS = "400"                         # kürzere Sprachantworten, begrenzt die Kosten
$env:JARVIS_LLM_BUDGET_ENABLED = "true"                    # Budget an (30 Aufrufe, 100 000 Token je Sitzung)
$env:JARVIS_LLM_BUDGET_MAX_CALLS = "30"
$env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "OpenAI-Schluessel" -AsSecureString)))
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -u -c "from jarvis.control_center.launcher import main; main()" -c config\nexus.voice-test.toml --open
```
Die Variablen gelten nur in diesem Fenster und enden mit ihm; der Schlüssel steht in keiner Datei. Vorher die laufende Instanz beenden (nur eine Instanz). Danach im Chat eine einfache Frage stellen: die Antwort muss vom Modell kommen (nicht „Hallo. Ich bin bereit.“); mit falschem Schlüssel kommt eine Fehlermeldung ohne Schlüssel.
**Zu erwartende Kosten (Größenordnung, nicht verbindlich):** ein Sprachdurchgang = Systemtext + Frage + Antwort ≈ 300–800 Token Eingabe und höchstens 400 Token Ausgabe (`max_tokens`). Die Obergrenze je Sitzung ist durch das Budget fest: 30 Aufrufe und 100 000 Token. Rechnung: Kosten ≤ 100 000/1000 × Preis je 1 000 Token (Eingabe/Ausgabe getrennt) des gewählten Modells; die aktuellen Preise stehen auf der Preisseite des Anbieters (hier nicht geprüft, kein Aufruf erfolgt). Für den Test mit einem kleinen Modell ist mit Cent-Beträgen oder weniger zu rechnen; ein hartes Eurolimit setzt `max_cost` plus `prices` in der TOML.
**Freigabe nötig für:** Provider-Umschaltung, jeder Aufruf mit Kosten, Änderung der Konfigurationsdatei.

## 9. Befund F-V-1: Sprachauftrag wird nur geplant, nicht ausgeführt (2026-11-20, read-only)
**Beobachtung:** Der gesprochene Auftrag „Erstelle dashboard-test.txt, schreibe JARVIS Test erfolgreich hinein, zeige die geöffneten Fenster und fasse das Ergebnis zusammen.“ ergab einen gespeicherten Plan mit sechs Schritten und den Hinweis „Ausführung später“.
**Nachgewiesen (Code):**
1. Die Sprachsitzung (`bootstrap.build_voice_session` -> `VoiceSession._handler.handle`) ruft direkt `core.handle(text)` auf. Dort entscheidet `looks_like_goal(text)`: Zielähnliche Sätze gehen an `core.plan` (Altweg: Plan formatieren und merken, **keine Ausführung**), alles andere an `chat`.
2. Der **Texteingabeweg** der Oberfläche geht dagegen zuerst durch `cli.research_route` (`gui_model._work_text`) und startet bei Recherche-/Dateisätzen das Ziel der Goal Engine (`/goal …`: Agenten -> `ToolRegistry.execute` -> PermissionEngine -> Freigabedialog). Dieser Zwischenschritt fehlt im Sprachweg.
3. Folge: Derselbe Satz getippt kann ein Ziel mit Freigaben starten, gesprochen nur den Altplan. „Plan gespeichert, Ausführung später“ ist die Antwort des Altwegs, kein Fehler der Ausführung und keine umgangene Freigabe.
**Zusätzlich (Parser, auch beim Tippen):** „schreibe … hinein“ erkennt `parse_file_goal` nicht; verlangt wird die Form „… mit dem Inhalt: …“. Dieser Satz würde auch getippt mit „fehlt der Inhalt“ erklärt.
**Einstufung:** Unterschied zwischen Sprach- und Textweg, in den Dokumenten nirgends als Absicht beschrieben. Keine Sicherheitsverletzung (nichts wurde ausgeführt).
**Mögliche Behebung (NICHT umgesetzt, braucht Freigabe, weil Sprache dann Ziele starten kann):** In `build_voice_session` den Handler so umhüllen, dass der Text vor `core.handle` durch `research_route` + `run_command` geht (gleicher Weg wie Tippen). Freigabedialoge, PermissionEngine, Notaus und die vorhandene `is_risky`-Bestätigung der Sprachsitzung blieben unverändert. Tests zuerst: (1) Dateisatz per Sprache startet ein Ziel statt Plan, (2) bei Notaus nichts, (3) riskanter Satz bleibt ohne „Bestätige“ gesperrt, (4) Freigabe wird weiterhin im Dialog verlangt. **Alternative:** Absicht dokumentieren („Sprache = Chat und Plan, Aufträge nur per Text“).
**Zum Testsatz:** Für einen sauberen Test sprich/tippe: „Erstelle die Datei dashboard-test.txt mit dem Inhalt: JARVIS Test erfolgreich“ (ein Auftrag je Satz; Fensterliste als eigener Satz).
