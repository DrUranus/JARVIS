# JARVIS

Modulares, persönliches KI-Assistenzsystem. Langfristiges Ziel: ein autonomer Agent, dem man ein Ziel nennt und der selbstständig
**denkt → plant → recherchiert → programmiert → handelt → testet → repariert → lernt → neue Fähigkeiten entwickelt**.

**Status: Phase 1 (Core MVP), Phase 2 (Voice), Phase 3 (Memory), Phase 13 (Permissions & Security, vorgezogen), Phase 4 (Computer Control), Phase 5 (Browser Agent v1), Phase 6 (Coding Agent v1) und Phase 7 (Multi-Agent-Orchestrierung v1), Phase 8 (Goal Engine v1) und Phase 9 (Self-Testing/Self-Repair v1) abgeschlossen (Linux + Windows validiert); Phase 10 (Business/Research/Finance v1) und Phase 11 (GUI, Tkinter) sind implementiert; von Phase 14 existieren nur Teilziele 1–4 (gemeinsamer Notaus, Sichtbarkeit laufender Arbeit, Autonomie-Invarianten als Tests, optionales Sitzungsbudget – alle standardmäßig aus bzw. ohne neue Autonomie, siehe `docs/PHASE14_AUTONOMY.md`); Phase 15 ist ein deaktivierter Vorschlagsworkflow; Phase 12 (Smartphone) ist nicht begonnen; die volle Testsuite lief zuletzt auf einem GitHub-Windows-Runner und auf Ubuntu grün (siehe `docs/TESTING.md`; Mikrofon, Lautsprecher, GUI und echter Browser bleiben manuell).** JARVIS plant und überwacht Ziele nur über die vorhandenen Agenten; es verändert weder sich selbst noch installiert es Fähigkeiten.

## Was bisher funktioniert (Phase 1–10, 13)

- Konfiguration (Defaults < TOML < Umgebungsvariablen), Dev-/Produktionsmodus, Logging, Fehlerhierarchie
- LLM-Abstraktion: `mock` (offline), `openai`, `anthropic`, `openai_compatible` (Ollama, LM Studio, llama.cpp-Server) – austauschbar per Konfiguration
- Core: Input → Kontext → Routing → LLM oder Planner → strukturierte `Response`
- Task-System mit Status-Automat, Subtasks, Ergebnis/Fehler, benötigten Tools/Agenten
- Tool-System: Registry, dynamische Registrierung, fehlerisolierte Ausführung, Permission-Level
- Planner: Ziel → Task mit Subtasks (LLM-JSON, mit Template-Fallback, damit nie „zu komplex“ zurückkommt)
- CLI (`jarvis>`)
- **Multi-Agent-Orchestrierung v1 (Phase 7):** `AgentOrchestrator` lässt Browser-, Coding-, Computer- und (Platzhalter-)Research-Agent auf strukturierten `AgentTask`s arbeiten – begrenzt parallel, mit Timeout, Abbruch, Abhängigkeiten und Ergebnisübergabe; fügt keine Fähigkeit hinzu, jede Aktion läuft weiter durch ToolRegistry → PermissionEngine
- **Goal Engine v1 (Phase 8):** Ziel → kurze, geprüfte Schrittfolge → Ausführung ausschließlich über den `AgentOrchestrator` → Auswertung → `SUCCEEDED/FAILED/BLOCKED/CANCELLED/TIMEOUT`; mit harten Grenzen (Schritte, Versuche, Timeouts), ohne neue Fähigkeit und ohne Selbstveränderung
- **Self-Testing / Self-Repair v1 (Phase 9):** Tests in einem ausdrücklich genannten Workspace ausführen, Fehler deterministisch diagnostizieren, eine **begrenzte** Reparatur über den bestehenden Coding-Agent durchführen lassen, gezielt und per Regression nachtesten – Erfolg nur, wenn beides grün ist und nur geplante Dateien geändert wurden; kein Self-Improvement, kein Git, keine Installation
- **Self-Improvement (Phase 15, standardmäßig aus, nur Vorschläge):** Verbesserungsvorschläge aus echten Laufdaten, signierter Speicher, Statusführung; vorgeschlagener Code wird **nicht** vorbereitet, getestet oder aktiviert (Isolation nicht nachgewiesen) – siehe Abschnitt „Self-Improvement“
- **Business / Research / Finance v1 (Phase 10):** drei echte Agenten im bestehenden Agent-System: Research liest öffentliche Seiten über das Browser-Tool und liefert belegte, klassifizierte (FACT/INFERENCE/OPINION/UNCERTAIN) Ergebnisse mit Quellen und Widersprüchen; Business macht daraus Markt-/Wettbewerbsanalysen, Businessplan-Rechnungen und Entwürfe; Finance rechnet Kennzahlen und Paper-Trades – **ohne** Echtgeld, Orders, Überweisungen oder Nachrichtenversand
- **Coding Agent v1 (Phase 6):** kontrollierte Softwareentwicklung in *einem* bestätigten Workspace – Projekt erkennen, lesen, suchen, ändern (hash-geschützt, mit Änderungszusammenfassung), Tests ausführen (ohne Shell, nur Allow-List), Git nur lesend; ein `coding`-Tool, eigener `CodingController`, jede Aktion durch ToolRegistry und PermissionEngine
- **Browser Agent v1 (Phase 5):** ein Browser (Playwright, optional) hinter austauschbaren Providern, gesteuert über **ein** `browser`-Tool – einzelne, einzeln bestätigte Schritte (öffnen, lesen, Elemente finden, klicken, ausfüllen, absenden, kontrolliert herunter-/hochladen); eigener `BrowserController`, getrennt von Computer Control
- **Computer Control (Phase 4):** Bildschirm, Maus, Tastatur, Fenster und Anwendungen als `ProtectedTool`s – jede Aktion läuft durch die Berechtigungs-Engine; opt-in, Windows-first (`pyautogui` + `mss` + Win32 über `ctypes`), austauschbare Provider
- **Permissions & Security (Phase 13):** Jede Tool-Ausführung läuft durch eine Berechtigungs-Engine (GREEN/YELLOW/RED, Regeln, Bestätigung, Pfad-Sicherheit, Audit-Log, Secret-Schutz) und schlägt im Zweifel fehl (fail closed)
- **Memory (Phase 3):** persistentes lokales Langzeitgedächtnis (SQLite) hinter der Schnittstelle `MemoryStore`, mit Secret-Schutz; gemerkt wird nur auf ausdrücklichen Wunsch
- **Voice (Phase 2):** Speech-to-Text → `JarvisCore.handle` → Text-to-Speech als zusätzliche Oberfläche, mit Wake-Word, Exit-Phrasen und Fallback bei fehlender Hardware
- **GUI (Phase 11):** Tkinter-Fenster um denselben Core: Text und Sprache, sichtbare Zustände, schreibgeschützter Status, sichere Bestätigungsdialoge (Abschnitt „Grafische Oberfläche“)

## Installation

Python ≥ 3.11. Keine Laufzeit-Abhängigkeiten.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Windows-Schnellstart

1. **Installation** (PowerShell, Python ≥ 3.11 von python.org, damit tkinter dabei ist):
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev,voice]"     # "voice" nur für Mikrofon/Lautsprecher; ohne geht es auch
   ```
2. **Prüfen:** `jarvis doctor` liest nur und meldet auf Deutsch: Python, tkinter, sounddevice/numpy, playwright, ob die Konfiguration gültig ist,
   welche Schlüsselvariablen *gesetzt/nicht gesetzt* sind (nie der Wert), welche Subsysteme aktiv sind und den Sicherheitsmodus.
   Exit-Code 0 = keine Fehler (Hinweise sind möglich), 1 = mindestens ein Fehler. Im Chat gibt es dasselbe als `/doctor`.
   Der Doctor schaltet nichts ein und schreibt nichts.
3. **Erster Start:** `jarvis` (Textmodus, ohne Schlüssel mit dem Offline-Modell `mock`). Für ein echtes Modell vorher z. B.
   `$env:JARVIS_LLM_PROVIDER="anthropic"; $env:ANTHROPIC_API_KEY="..."` setzen (nur per Umgebung, nie in Dateien).
4. **GUI:** `jarvis-gui` (Tkinter-Fenster um denselben Core, siehe „Grafische Oberfläche“).
5. **Was ausgeschaltet ist:** Computersteuerung, Browser-Agent, Coding-Agent, Agenten, Ziele, Selbstreparatur, Selbstverbesserung, Research, Business, Finance
   und das Sitzungsbudget stehen in `config/jarvis.toml` auf `enabled = false`; Replanning ist aus, Finance bleibt nur Paper-Trading, der Sicherheitsmodus ist
   `standard` (Rückfrage bei YELLOW, RED nie erlaubt). Einschalten nur bewusst in der Konfiguration, jede Aktion läuft weiter durch die Berechtigungsprüfung.
   Der Notaus ist `/notaus` bzw. der rote Knopf in der GUI.

## Konfiguration

Vorrang (niedrig → hoch): eingebaute Defaults → `config/jarvis.toml` (oder `jarvis.local.toml`, `-c PFAD`, `JARVIS_CONFIG`) → Umgebungsvariablen.

| Variable | Bedeutung |
|---|---|
| `JARVIS_MODE` | `development` (Log DEBUG) / `production` (Log INFO) |
| `JARVIS_LOG_LEVEL`, `JARVIS_LOG_DIR` | Logging |
| `JARVIS_LLM_PROVIDER` | `mock` (Default), `openai`, `anthropic`, `openai_compatible` |
| `JARVIS_LLM_ALLOW_REMOTE` | `false` (Default); nur `openai_compatible`: erlaubt eine Nicht-Loopback-`base_url` |
| `JARVIS_LLM_MODEL`, `_TEMPERATURE`, `_MAX_TOKENS`, `_TIMEOUT`, `_BASE_URL` | Modell-Parameter |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_COMPATIBLE_API_KEY` / `JARVIS_LLM_API_KEY` | API-Keys (nur per Umgebung, nie in Dateien) |

Lokales Modell (`openai_compatible`, ohne neue Bibliothek): `JARVIS_LLM_PROVIDER=openai_compatible JARVIS_LLM_BASE_URL=http://127.0.0.1:11434/v1 JARVIS_LLM_MODEL=<modell> jarvis`.
Standard sind nur Loopback-Ziele (`localhost`, `127.0.0.0/8`, `::1`); ein entferntes Ziel braucht `llm.allow_remote = true`, `https` und einen Schlüssel aus der Umgebung. Der Schlüssel ist auf Loopback optional, steht nie in einer Datei (ein `llm.api_key` in der TOML-Datei wird für diesen Anbieter abgelehnt), nie in Logs oder Fehlermeldungen; Weiterleitungen werden nicht verfolgt. Der Coding Agent behandelt jeden Anbieter außer `mock` als „EXTERN“ (auch Loopback; bewusst vorsichtig). Kein Streaming. Details: `docs/integrations/llm-openai-compatible.md`.

Beispiel mit echtem Modell: `JARVIS_LLM_PROVIDER=anthropic JARVIS_LLM_MODEL=<modell> ANTHROPIC_API_KEY=... jarvis`

## Start

```bash
jarvis            # oder: python -m jarvis.interface.cli
```
```
jarvis> Hallo JARVIS
Hallo. Ich bin bereit.
jarvis> Erstelle ein Python-Programm, das eine CSV-Datei analysiert.
Plan für: ...  [Task 1f23c6a6]
  1. Anforderungen analysieren ...
```
CLI-Befehle: `/plan <ziel>`, `/tasks`, `/tools`, `/reset`, `/doctor`, `/help`, `/exit`. Eingaben, die mit einem Aufgabenverb beginnen
(„erstelle“, „build“, …), werden automatisch geplant, alles andere ist Dialog.

## Voice-Interface (Phase 2)

```
AudioSource (Mikrofon) ─▶ STTProvider ─▶ text ─▶ JarvisCore.handle ─▶ Response ─▶ TTSProvider ─▶ Lautsprecher
        └──────── SpeechListener ───────┘                                └──── TTSSpeaker ────┘
                          └──────────────── VoiceSession (Schleife, Wake-Word, Fehlerbehandlung) ──────┘
```

Austauschbare Schnittstellen (`voice/base.py`): `AudioSource`, `AudioPlayer`, `STTProvider`, `TTSProvider`, sowie `Listener`/`Speaker`
(Text rein / Text raus). `VoiceSession` hängt nur von einem Objekt mit `handle(text) -> Response` ab – nicht von `JarvisCore` selbst.

| Rolle | Name in Konfiguration | Hinweis |
|---|---|---|
| Eingabe | `console` | Default. Getippte Zeilen gelten als Sprache, Ausgabe wird mit 🔊 gedruckt. Läuft überall, ohne Hardware/Key |
| STT | `openai` | Whisper-API, braucht `OPENAI_API_KEY` oder `JARVIS_VOICE_API_KEY`; `base_url` für kompatible Server |
| STT | `mock` | nur Tests |
| Mikrofon | `sounddevice` | optional: `pip install -e ".[voice]"` (benötigt die PortAudio-Systembibliothek). Einfache Stille-Erkennung beendet die Aufnahme |
| TTS | `system` | offline über `espeak-ng`, `espeak`, `spd-say` oder `say` (macOS); eigener Befehl via `tts_command` |
| TTS | `openai` | Sprachsynthese-API + `audio_output` (`system`: afplay/paplay/aplay/ffplay, oder `null`) |
| TTS | `console`, `mock` | Ausgabe drucken / Tests |

### Einrichtung

Ausprobieren ohne Hardware:
```bash
jarvis --voice          # oder im Dialog: /voice   – Sprachmodus verlassen mit „exit“
```
Echte Sprache (Beispiel: Whisper-STT + lokale TTS):
```bash
pip install -e ".[voice]"            # Mikrofon
sudo apt install portaudio19-dev espeak-ng   # Linux; macOS: brew install portaudio (TTS: eingebautes `say`)
export OPENAI_API_KEY=...
JARVIS_VOICE_STT_PROVIDER=openai JARVIS_VOICE_TTS_PROVIDER=system \
JARVIS_VOICE_REQUIRE_WAKE_WORD=true jarvis --voice
```
Wake-Word-Verhalten: Mit `require_wake_word = true` werden Äußerungen ohne „JARVIS“ ignoriert. Sagt man nur „JARVIS“, antwortet
er „Ja?“ und nimmt die nächste Äußerung ohne Wake-Word an. „JARVIS, was ist offen?“ wird als „was ist offen?“ an den Core gegeben.
Das Wake-Word wird auf dem *Transkript* erkannt (Phase-2-Kompromiss, siehe unten). Optional kann ein lokaler Hotword-Baustein davor geschaltet werden (siehe „Barge-in und Hotword“).
Exit-Phrasen: `exit`, `quit`, `stop`, `stopp`, `beenden`, `beende`, `tschüss`, `goodbye`.

Konfiguration im Abschnitt `[voice]` von `config/jarvis.toml` oder per `JARVIS_VOICE_<FELD>`
(`STT_PROVIDER`, `TTS_PROVIDER`, `AUDIO_INPUT`, `AUDIO_OUTPUT`, `LANGUAGE`, `WAKE_WORD`, `REQUIRE_WAKE_WORD`, `SPEAK_RESPONSES`,
`SAMPLE_RATE`, `MAX_RECORD_SECONDS`, `SILENCE_SECONDS`, `SILENCE_THRESHOLD`, `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`, `TTS_COMMAND`,
`BASE_URL`, `TIMEOUT`). API-Keys nur über die Umgebung.

### Barge-in und Hotword (Phase 2)

- **Barge-in:** `AudioPlayer.stop()`, `TTSProvider.stop()` und `Speaker.stop()` (Default: tut nichts) sowie `VoiceSession.interrupt()` beenden eine laufende Sprachausgabe.
  `interrupt()` stoppt nur die Ausgabe – es führt keinen Befehl aus und bestätigt nichts. Grenze: `SystemPlayer` kann nur unter Windows (sounddevice) abbrechen; die externen
  POSIX-Player und `SystemTTS` laufen bis zum Ende. Es gibt keinen Hintergrund-Lauscher, der selbst unterbricht; der Aufruf kommt vom Interface.
- **Hotword:** `HotwordDetector.detect(clip) -> bool` (lokal, ohne Netzwerk). `HotwordGatedSource` setzt ihn vor jeden `AudioSource`: `record()` liefert `None`, bis das Hotword
  erkannt wurde; erst die nächste Aufnahme ist der Befehl. Wahl per `voice.hotword_detector` (Default `none`, `mock` für Tests), eigene Detektoren per
  `register_hotword_detector("name", factory)`. Es wird **kein** echter Detektor mitgeliefert. Der Befehl läuft danach wie immer über `core.handle` ->
  `ToolRegistry.execute` -> `PermissionEngine`; das Hotword löst nie eine Aktion aus und ersetzt nie eine Bestätigung. Notaus-Verhalten ist unverändert.

Eigenen Anbieter hinzufügen: `STTProvider`/`TTSProvider` implementieren und per `register_stt("name", factory)` /
`register_tts(...)` / `register_audio_source(...)` registrieren – danach per Konfiguration wählbar, ohne Core-Änderung.

### Verhalten bei Problemen
- Mikrofon-Bibliothek, Audiogerät, TTS-Programm oder API-Key fehlt beim Start → Meldung „Sprachmodus nicht verfügbar: …“, die Text-CLI läuft weiter.
- Ausgabegerät fällt aus → einmalige Meldung, danach nur Text (kein Abbruch). TTS-Fehler einzelner Antworten → Text bleibt sichtbar.
- STT-Fehler → Schleife läuft weiter; nach 3 Fehlern in Folge wird der Sprachmodus beendet. Mikrofonausfall beendet ihn sofort, mit Meldung.
- Pläne werden gesprochen nur zusammengefasst („Plan mit 6 Schritten …“), der volle Plan steht auf dem Bildschirm.

## Memory (Phase 3)

```
Core ──▶ MemoryStore (Interface) ◀── GuardedMemoryStore (Secret-Filter, Limits) ◀── SqliteMemoryStore | InMemoryStore | (künftig: Vektor/…)
  │
  └─ MemoryExtractor (RuleBasedExtractor): erkennt „Merk dir …“ / „Woran erinnerst du dich?“ / „Vergiss …“
```

**Temporär vs. dauerhaft.** Der Gesprächsverlauf (`Context`) bleibt flüchtig. Dauerhaft wird nur gespeichert, was der Nutzer ausdrücklich verlangt
(„Merk dir, dass …“, `/remember …`) oder was Code bewusst über die API speichert (`core.remember(...)`, später z. B. Task-Ergebnisse oder Agenten).
Es gibt keine automatische Extraktion; die Extraktionslogik steht hinter `MemoryExtractor` und ist austauschbar.

**Datenmodell** (`MemoryEntry`): `id` (12 Hex), `content`, `type` (`preference`, `fact`, `project`, `goal`, `decision`, `task_result`,
`conversation`, `system`, `resource`), `importance` (1–10, 10 = wichtigst), `tags`, `source` (z. B. `user`, `agent:research`),
`metadata` (JSON, z. B. Dateipfade), `created_at`, `updated_at`.

**Schnittstelle** (`MemoryStore`): `add`, `get`, `search`, `update`, `delete`, `recent` (auch paginiert/gefiltert), `count`, `close`.
Fehler sind immer `MemoryStoreError`-Unterklassen (`MemoryValidationError`, `SecretRejectedError`, `MemoryNotFoundError`, `MemoryLimitError`, `MemoryDisabledError`).

**Suche** (`ranking.py`): Schlüsselwörter, ohne Stoppwörter, Teilstring-Treffer („Farbe“ findet „Lieblingsfarbe“), Rang nach Trefferanteil, Tag-Bonus,
Wichtigkeit, Aktualität. Treffer liefern `MemoryHit(entry, score)`; ein späteres semantisches Backend ersetzt nur die Bewertung.
Optional (`backend = "semantic"`): lokale, netzfreie Ähnlichkeitssuche (gehashte TF-IDF-Vektoren über Zeichen-3/4-Gramme, nur Standardbibliothek, `jarvis.memory.semantic`); sie findet Flexionen und Komposita (‚Farben‘ → ‚Lieblingsfarbe‘), bewertet die neuesten 500 Kandidaten und sendet nichts. Speicherung, Secret-Schutz und ‚nur auf ausdrücklichen Wunsch merken‘ bleiben unverändert; der Standard ist weiter `sqlite`.

**Dialog und CLI**
| Eingabe | Wirkung |
|---|---|
| „Merk dir, dass meine Lieblingsfarbe blau ist“ / `/remember …` | speichert (Typ wird per Schlüsselwörtern geschätzt; „wichtig“ → Wichtigkeit 8) |
| „Woran erinnerst du dich?“, „Was weißt du über mich?“ / `/memory [suche]` | listet neueste bzw. passende Erinnerungen |
| „Vergiss `<id>`“ / `/forget <id>` | löscht genau diese Erinnerung |
| „Vergiss dass ich Kaffee mag“ | listet nur Kandidaten mit IDs – **unscharfe Treffer löschen nie** |

Diese Anfragen werden lokal bearbeitet, gehen nie an das LLM und landen nicht im Gesprächsverlauf. Bewusst eng gefasst: „Was weißt du über Quantenphysik?“ bleibt eine normale LLM-Frage.

### Konfiguration `[memory]`

| Schlüssel / Variable | Default | Bedeutung |
|---|---|---|
| `enabled` / `JARVIS_MEMORY_ENABLED` | `true` | `false` → `NullMemoryStore`: Lesen leer, „Merk dir“ antwortet „deaktiviert“ |
| `backend` / `JARVIS_MEMORY_BACKEND` | `sqlite` | `sqlite`, `memory` (nicht persistent), `semantic` (SQLite + lokale Ähnlichkeitssuche) oder `semantic-memory` (nicht persistent); eigene via `register_backend` |
| `path` / `JARVIS_MEMORY_PATH` | `data/memory.db` | wird beim ersten Schreiben samt Ordner angelegt; `~` wird aufgelöst |
| `max_relevant` / `JARVIS_MEMORY_MAX_RELEVANT` | `5` | max. Erinnerungen pro Anfrage (`0` = keine automatische Nutzung) |
| `recent_limit` | `10` | Standardgröße von „neueste“-Listen |
| `max_content_length` | `2000` | Zeichen pro Eintrag (harte Obergrenze 10 000) |
| `max_entries` | `10000` | `0` = unbegrenzt; danach `MemoryLimitError` |
| `use_in_prompts` / `JARVIS_MEMORY_USE_IN_PROMPTS` | `false` | **Datenschutz-Schalter**, siehe unten |

### Datenschutz und Sicherheit
- **Lokal:** Das Memory-Paket sendet nichts. Die Datenbank liegt in `data/` (git-ignoriert).
- **`use_in_prompts`:** Nur wenn `true`, werden zur Anfrage passende Erinnerungen als temporäre System-Notiz an das LLM (und den Planner) angehängt – bei
  `openai`/`anthropic` verlassen sie dann den Rechner. Deshalb standardmäßig aus; die Notiz wird nicht im Verlauf gespeichert und die Erinnerungen werden als Daten, nicht als Anweisungen markiert.
- **Secrets werden nie gespeichert** (`SecretGuard`, Pflicht-Schicht von `create_memory`): bekannte Schlüsselformate (`sk-…`, `ghp_…`, AWS, Slack, Google, JWT, PEM-Keys),
  Aussagen wie „Passwort ist …“/`api_key=…`/`token: …`, Zugangsdaten in URLs, lange Zufallstokens sowie die **exakten Werte** der laufenden Konfiguration
  (`llm.api_key`, `voice.api_key`) und aller Umgebungsvariablen mit `KEY/SECRET/TOKEN/PASSWORD` im Namen. Geprüft werden Inhalt, Tags, Quelle und Metadaten, bei `add` und `update`.
  Der Fehler nennt nie den Wert. Konservativ: lieber ein Fehlalarm („Mein Passwort ist sicher“) als ein gespeichertes Geheimnis.
- **SQL:** ausschließlich parametrisierte Abfragen; LIKE-Wildcards in Suchbegriffen werden maskiert.
- **Robustheit:** fehlende DB → leere Ergebnisse ohne Anlegen einer Datei; leere Datei → Schema wird angelegt; beschädigte oder neuere Datenbank → `MemoryStoreError`, Datei bleibt unangetastet; Memory-Fehler brechen nie den normalen Dialog (nur ausdrückliche Memory-Anfragen melden sie).

### Memory aus anderen Modulen nutzen
Künftige Agenten/Tools bekommen ein `MemoryStore` injiziert (z. B. `core.memory`) und rufen `add(..., type="task_result", source="agent:coding", metadata={"path": ...})`,
`search`, `recent`. Sie hängen nur von `jarvis.memory.base`/`models` ab, nie von SQLite.

## Verlauf abgeschlossener Arbeit (`[history]`, optional)

Ziele, Agenten-Tasks, Reparaturläufe und gespeicherte Pläne liegen im laufenden Betrieb nur im Speicher. Mit `history.enabled = true` (bzw. `JARVIS_HISTORY_ENABLED=true`) übernimmt ein kleiner lokaler SQLite-Speicher (`history.path`, Standard `data/history.db`, Datei entsteht erst beim ersten Schreiben) **nur abgeschlossene** Einträge: Art, ID, Status, Kurztext, Zeiten und Fehlergrund. Standard: **aus** (keine Datei, Verhalten unverändert).

- **Nur Historie und Anzeige.** Nach einem Neustart wird nichts fortgesetzt und nichts gestartet; offene Arbeit gilt als verloren. Angezeigt wird der Verlauf mit `/history [n]` (CLI) und im GUI-Reiter *Status* (Abschnitt "Laufende Arbeit", Zeilen "Verlauf"). Der Speicher liest nur (`list`/`result`), er startet, erstellt, setzt fort oder bricht nichts ab (Strukturtest).
- **Aufgenommen** wird beim Ende von `run_goal`/`run_repair`, nach `cancel_goal`/`cancel_repair`, beim Lesen der Historie, beim GUI-Status und bei `/exit`. Ein Absturz verliert höchstens, was seit der letzten Aufnahme endete.
- **Datenschutz.** Jeder Text läuft vor dem Schreiben durch die gemeinsame Redaktion (`jarvis.redaction`: bekannte Schlüsselformate, "password=…", Werte aus Konfiguration/Umgebung) und wird auf `history.max_text_length` (Standard 300) gekürzt; IDs mit Secrets werden abgelehnt. Es werden weder Schritt-Ergebnisse noch Ausgaben noch Bilder gespeichert.
- **Obergrenze.** `history.max_entries` (Standard 500, hart 100000): die ältesten Einträge fallen zuerst weg.
- **Fehler.** Eine kaputte oder fremde Datei wird nie überschrieben; Lese-/Schreibfehler brechen weder Core noch GUI ab (Warnung im Log).
- Verdrahtung nur in `bootstrap.py`; der Core kennt den Speicher nur als `core.history` (duck-typed). Tests: `tests/test_history_store.py`. Ein `[history]`-Abschnitt in `config/jarvis.toml` fehlt noch (die Routine durfte `config/` nicht ändern); die Code-Standardwerte (aus) gelten.

## Permissions & Security (Phase 13)

Die Berechtigungsschicht sitzt zwischen JARVIS und jedem mächtigen Werkzeug und ist unabhängig von Voice, Memory, LLM-Anbietern und konkreten Tools
(Import-Regeln sind per Test erzwungen; sie hängt nur von `jarvis.errors` und dem neutralen `jarvis.redaction` ab).

```
Interface ─▶ Core ─▶ Planner/Tasks ─▶ ToolRegistry.execute ─▶ PermissionEngine ─▶ Policy · Pfad-/Host-Prüfung · Bestätigung ─▶ tool.run
                                       (einziger Aufrufer von tool.run)           └─ AuditLogger (Secrets geschwärzt)
```

### Ablauf einer Ausführung
1. Das **Tool beschreibt** den konkreten Aufruf (`describe_action` → `ActionSpec`: Aktion, Ressource, Grund). Es spricht nie selbst mit der Engine.
2. Die **Registry** baut daraus eine `PermissionRequest` (Tool, Aktion, Ressource + Typ, Level, Grund, Kontext, ID, Zeitstempel, Argument-Fingerabdruck).
3. Die **Engine** entscheidet: ungültig → `INVALID_REQUEST`; RED → `DENIED`; Lockdown; Dateipfade/Hosts normalisieren und prüfen; Regeln (deny > confirm > allow);
   sonst Level-Standard (GREEN erlaubt, YELLOW fragt). Ergebnis ist immer eine `PermissionDecision` mit `status`, `reason`, `matched_rule`, `scope`, `level`.
4. Bei `CONFIRMATION_REQUIRED` fragt ein **`ConfirmationProvider`** den Nutzer (CLI heute; Voice/GUI/App später über dieselbe Schnittstelle).
5. Nur bei `ALLOWED` öffnet die Engine einen **einmaligen Ausführungs-Scope**; erst darin läuft `tool.run`. Ergebnis und Entscheidung stehen im `ToolResult`.

Entscheidungsstatus: `allowed`, `denied`, `confirmation_required`, `invalid_request`, `policy_error`, `internal_error` (alle außer `allowed`/`confirmation_required` sind Ablehnungen).
Jede Ausnahme in der Engine, jeder fehlerhafte Provider, jede kaputte Regel und ein nicht schreibbares Audit-Log (bei nicht-GREEN) enden in einer Ablehnung, nie in einer Freigabe.

### Level
| Level | Bedeutung | Verhalten |
|---|---|---|
| GREEN | sicher, lesend, Analyse, Planung, Tests | automatisch (nur Ablehnungen und Folgenreiches werden geloggt) |
| YELLOW | ändert etwas / Außenwirkung / Geld | Bestätigung, oder eine bewusst konfigurierte `allow`-Regel |
| RED | gefährlich/verboten | **immer abgelehnt**; keine Regel, Sitzung, Bestätigung, Modus oder Konfiguration schaltet das frei (eine `allow`-Regel für RED wird beim Laden abgelehnt) |

Das Level setzt das Tool (`permission`). Die Engine kann es nur **anheben**: Aktionsnamen mit Folgen (`write`, `delete`, `send`, `execute`, `pay`, …) sind mindestens YELLOW, egal was ein Tool behauptet.
Nicht deklarierte Tools zählen in der Anwendung als YELLOW.

### Regeln (`security.policy_file`, Beispiel `config/policy.example.toml`)
Felder: `id`, `effect` (`deny`/`confirm`/`allow`), `tool`, `action` (exakt oder Glob), `resource_type` (`path`/`domain`/`other`), `resources`, `levels`, `description`.
- **Deterministisch:** Es gewinnt der sicherste Effekt (deny > confirm > allow), unabhängig von der Reihenfolge; Gleichstand entscheidet die ID. Alle passenden Regeln stehen in `considered_rules`.
- **Sicher bei fehlenden Infos:** deny/confirm-Regeln mit Ressourcenbedingung greifen auch, wenn die Anfrage keine Ressource nennt; `allow`-Regeln nie.
- **Kein Wildcard-Zugriff:** `allow` braucht einen exakten Tool-Namen und eine Aktion; `*`, `/`, `*.*`, `*.com` als Ressource werden abgelehnt.
- Pfadregeln vergleichen echte (aufgelöste) Pfade; deny/confirm-Regeln ignorieren Groß-/Kleinschreibung, `allow`-Regeln nicht.
- Eine fehlende oder fehlerhafte Policy-Datei ist ein **Startfehler** (JARVIS startet nicht mit einer unbeabsichtigten Policy).

### Bestätigung, Freigaben, Sitzungen
- Der Nutzer sieht Aktion, Werkzeug, **echten Pfad** (Symlinks aufgelöst, angefragter Pfad zusätzlich), Risiko, Grund. Beispiel: `JARVIS möchte die Aktion „write“ mit „filesystem“ auf /ws/a.txt ausführen. … Risiko: YELLOW … Erlauben?`
- **Einmalig:** gilt für genau diesen Aufruf (Argumente per Fingerabdruck gebunden), wird beim Ausführen verbraucht, läuft nach 60 s ab.
- **Sitzung:** nur nach ausdrücklicher Antwort „s“, gebunden an exakt (Tool, Aktion, echte Ressource, Level), läuft ab (`session_ttl_seconds`), widerrufbar (`/revoke`), wird bei Policy-Änderung widerrufen, begrenzt auf 100 Einträge. Bei `confirm`-Regeln („immer fragen“) wird sie gar nicht angeboten.
- **Dauerhaft:** ausschließlich explizite `allow`-Regeln. Nichts wird implizit gelernt oder gespeichert.
- `CliConfirmation`: nur `j/ja/y/yes` (einmal) und `s/sitzung/session` erlauben; leere Eingabe, Unbekanntes, EOF und Strg-C bedeuten Nein. `confirmation = "deny"` (headless) fragt nie und lehnt YELLOW ab.
- Für Voice/GUI: `ConfirmationProvider.confirm(ConfirmationRequest) -> ConfirmationChoice` implementieren (`request.summary` ist ein sprechbarer Satz) und per `engine.set_confirmation_provider(...)` (auditiert) setzen.

### Dateisystem-Grundlage (`PathGuard`)
Noch kein Dateisystem-Tool, aber die Prüfung, die jedes künftige durchlaufen muss: standardmäßig **nur das Workspace-Verzeichnis** (`security.allowed_roots` erweitert, `denied_paths` sperrt), leere Liste = alles verboten, die Dateisystemwurzel `/` ist nie erlaubt.
Relative Pfade werden gegen das Basisverzeichnis (nicht das cwd) aufgelöst; `..`-Varianten und `./`, `//`, Schrägstrich am Ende werden normalisiert; Symlinks werden aufgelöst (auch `link/../x` nach OS-Semantik);
Enthaltensein wird komponentenweise geprüft (`/ws-evil` liegt nicht in `/ws`); NUL-/Steuerzeichen und überlange Pfade sind ungültig. Policy- und Audit-Datei sind gegen Änderung durch Tools geschützt. Die Entscheidung enthält den echten Pfad (`ExecutionGrant.resource`), den das Tool verwenden soll.
Hosts (`ResourceType.DOMAIN`) werden normalisiert (URL → Host, Kleinbuchstaben, IDNA, keine Zugangsdaten in der URL); `example.com` = exakt, `*.example.com` = echte Subdomains.

### Secrets
`jarvis.redaction.SecretDetector` (derselbe Detektor wie beim Memory-`SecretGuard`, plus die exakten Werte von `llm.api_key`, `voice.api_key` und aller `*KEY/SECRET/TOKEN/PASSWORD*`-Umgebungsvariablen) schwärzt
Entscheidungsgründe, Bestätigungstexte, Audit-Ereignisse, Fehlermeldungen und Logzeilen abstürzender Tools. Kontextwerte unter Schlüsseln wie `api_key`/`password` werden immer geschwärzt.
`repr(PermissionRequest)` zeigt bewusst keine Freitextfelder.

### Audit-Log (`logs/audit.jsonl`, austauschbar über `AuditSink`)
JSON Lines, Dateirechte 0600, wird beim ersten Ereignis angelegt. Ereignisse: `permission_requested/granted/denied`, `confirmation_requested/accepted/rejected`, `session_grant_created`, `session_grants_revoked`,
`policy_loaded/changed` (inkl. Fingerabdruck, hinzugefügte/entfernte Regeln), `tool_registered` (nicht-GREEN), `execution_result` (nicht-GREEN), `caller_confirmation_ignored`, `security_error`.
Gespräche werden nie protokolliert; GREEN nur mit `audit_green = true`. `/audit [n]` zeigt die letzten Ereignisse. Schreibt das Log nicht, werden nicht-GREEN-Aktionen abgelehnt (`audit_strict`).

### Konfiguration `[security]`
| Schlüssel / Variable `JARVIS_SECURITY_…` | Default | Bedeutung |
|---|---|---|
| `mode` / `MODE` | `standard` | `standard` oder `lockdown` (nur GREEN, nichts anderes). Es gibt absichtlich keinen „permissive“-Modus |
| `confirmation` / `CONFIRMATION` | `cli` | `cli` fragt im Terminal, `deny` fragt nie (YELLOW abgelehnt) |
| `policy_file` / `POLICY_FILE` | – | TOML mit Regeln |
| `allowed_roots` / `ALLOWED_ROOTS` | `[]` = nur `workspace` | erlaubte Verzeichnisse (Umgebungsvariable: mit `:` getrennt) |
| `denied_paths` / `DENIED_PATHS` | `[]` | immer gesperrt |
| `allow_session_grants`, `session_ttl_seconds` | `true`, `3600` | Sitzungsfreigaben |
| `audit_enabled`, `audit_path`, `audit_strict`, `audit_green` | `true`, `<log_dir>/audit.jsonl`, `true`, `false` | Audit |

Alle Defaults sind restriktiv; zum Starten ist nichts zu konfigurieren.

### Ausprobieren (Entwicklungsmodus)
```
jarvis> /run permission_demo target=notes.txt     # YELLOW: JARVIS fragt; das Demo-Tool verändert nichts
jarvis> /run permission_demo target=../../etc/passwd   # ohne Rückfrage abgelehnt (außerhalb des Workspace)
jarvis> /permissions    /audit 20    /revoke
```

### Neue Tools schreiben
GREEN: `Tool` mit `permission = PermissionLevel.GREEN` und `run`. Alles andere: `ProtectedTool` ableiten, `_perform` implementieren (nie `run` – das wird beim Definieren der Klasse abgelehnt),
`describe_action` überschreiben (Aktion, Ressource + `ResourceType`, Grund), `permission` deklarieren. `describe_action` darf keine Nebenwirkungen haben (es läuft vor der Entscheidung).
Dateipfade immer über `current_grant().resource` (den freigegebenen echten Pfad) verwenden.

### Bekannte Grenzen
- **Gleicher Prozess = gleiche Vertrauensgrenze.** Python kann Code im selben Prozess nicht einsperren. Die Schicht verhindert versehentliche und naheliegende Umgehungen (Tests dafür vorhanden), nicht absichtlich bösartigen Code mit Zugriff auf Interna oder `ctypes`. Echte Isolation (Subprozess/Container/OS-Sandbox) gehört zu Phase 4/14/15.
- Ein GREEN-Tool, das lügt, kann außer durch den Aktionsnamen-Boden und deny/confirm-Regeln pro Tool nicht erkannt werden.
- Pfadprüfung ist eine Momentaufnahme (TOCTOU zwischen Prüfung und Öffnen): künftige Dateitools müssen den freigegebenen echten Pfad verwenden und möglichst ohne Symlink-Folgen öffnen (`O_NOFOLLOW`). Hardlinks, Windows-Kurznamen (8.3), NTFS-Datenströme und Unicode-Normalisierung (macOS) werden nicht gesondert behandelt; Allow-Regeln sind case-sensitiv (sicher), Deny-Regeln nicht (sicher).
- Das Audit-Log ist nicht manipulationssicher (keine Hash-Kette, keine Rotation); es schützt nur davor, dass JARVIS-Tools es ändern.
- Die CLI-Bestätigung blockiert ohne Zeitlimit. Der Gesprächsverlauf mit Secrets, die der Nutzer selbst tippt, geht weiterhin an das LLM (nicht Teil dieser Phase).
- `PermissionEngine.legacy()` (für ein nacktes `ToolRegistry()`, Phase-1-Kompatibilität) ist locker: nicht deklarierte Tools GREEN, `confirmed=True` des Aufrufers gilt. Die Anwendung, `JarvisCore` und `Planner` verwenden strikte Registries (per Test erzwungen).

## Computer Control (Phase 4)

JARVIS kann – **nur wenn du es aktivierst** – Bildschirm, Maus, Tastatur, Fenster und Anwendungen bedienen. Alles läuft durch die bestehende
Berechtigungs-Engine aus Phase 13; es gibt kein zweites Rechtesystem und keine Abkürzung.

```
Voice/CLI/GUI → Core → Planner/Tasks → Tool (screen, mouse, keyboard, window, app, screen_save) → ToolRegistry
              → PermissionEngine → Policy / Bestätigung → ComputerController → Provider → Windows (oder X11) → PC
```
Der Core importiert weder `jarvis.computer` noch eine Automationsbibliothek (per Test erzwungen). `bootstrap` baut ein *Subsystem*
(Tools in der Registry + Sicherheitsregeln in der Engine), das der Core nur als opaken Eintrag in `core.subsystems` hält.

### Einrichtung (Windows)
```powershell
pip install -e ".[computer]"                     # pyautogui + mss (optional; JARVIS startet auch ohne)
$env:JARVIS_COMPUTER_ENABLED = "true"            # oder in config/jarvis.toml: [computer] enabled = true
jarvis                                           # /computer zeigt Status; /run screen action=monitors
```
Ohne Bibliothek, ohne Display oder auf einem anderen System bleibt Computer Control **ausgeschaltet** und `/computer` nennt den Grund
(`nicht verfügbar – [no_display] …`); JARVIS und die CLI laufen normal weiter. Anwendungen müssen als Alias freigegeben werden:
```toml
[computer.apps]
notepad = "%SystemRoot%\\System32\\notepad.exe"     # unter Windows sind Notepad/Rechner/Paint standardmäßig dabei
```
Linux/Entwicklung: Backend `x11` (benötigt X11, `python-xlib` und `python3-tk`, weil `pyautogui` sonst beim Import beendet; JARVIS fängt das ab).
Backend `fake` simuliert einen kleinen Desktop ohne Hardware (`JARVIS_COMPUTER_BACKEND=fake`).

### Werkzeuge
| Tool | Level | Aktionen | Ressource (was die Engine sieht) |
|---|---|---|---|
| `screen` | GREEN | `monitors`, `screenshot` (`monitor=0|all`), `compare` (`a`,`b`), `windows`, `active_window`, `cursor`, `forget` | `screen://monitor/0`, `screen://all`, `screen://windows`, … |
| `screen_save` | YELLOW | Screenshot (`id`) als `.png` in einen erlaubten Ordner schreiben | echter Pfad (PathGuard), nie überschreiben |
| `mouse` | YELLOW | `move`, `click`, `double_click`, `right_click`, `scroll` (`x`,`y`,`monitor`,`amount`) | `screen://monitor/0/120/340` |
| `keyboard` | YELLOW (immer gefragt) | `press` (`key`), `hotkey` (`keys=ctrl+s`), `type` (`text`) | `keyboard://key/ENTER@notepad.exe`, `keyboard://hotkey/CTRL+S@…`, `keyboard://text@notepad.exe` (**nie der Text**) |
| `window` | YELLOW (`close` immer gefragt) | `focus`, `minimize`, `maximize`, `restore`, `close` (`handle`) | `window://66012/notepad.exe` |
| `app` | YELLOW | Alias starten (`app`, `args`) | `app://C:/Windows/System32/notepad.exe` (+ `?args=<digest>`) |

Aufruf von Hand: `/run mouse action=click x=100 y=200`, `/run keyboard action=type text="Hallo"`, `/run app app=notepad`.
Koordinaten sind **monitor-relativ**; Monitor 0 ist der primäre. Eine Policy-Regel kann die URIs mit Globs treffen, z. B. `resources = ["keyboard://*@notepad.exe"]`.

### Sicherheitsmodell
- **Konservative Klassifikation:** Beobachten ist GREEN; jedes Handeln (auch `move`/`scroll`/`focus`) ist mindestens YELLOW und wird bestätigt. Die Engine hebt Aktionen wie `click`, `type`, `close`, `launch` zusätzlich selbst auf YELLOW, egal was ein Tool behauptet.
- **RED (immer abgelehnt, nicht konfigurierbar):** Terminals/Shells/Skript-Hosts/System- und Sicherheitswerkzeuge (cmd, PowerShell, wscript, python, regedit, Task-Manager, Windows Security …) als Eingabeziel, zu startendes Programm oder zu schließendes Fenster; Windows-Taste und `Strg+Alt+Entf`/`Strg+Umschalt+Esc`/`Strg+Esc`; nicht freigegebene Anwendungen; Desktop-Shell, Systemprozesse und JARVIS' eigenes Fenster beim Schließen. Die Konfiguration kann diese Listen nur **erweitern** (`blocked_processes`, `blocked_titles`; Standard: `explorer.exe`). RED-Anfragen werden im Audit-Log mit Grund festgehalten.
- **Immer fragen:** Baseline-Regeln (`computer-baseline-*`, sichtbar in `/permissions`) erzwingen die Rückfrage bei jeder Tastatureingabe und jedem Schließen eines Fensters, ohne Sitzungsfreigabe; eine `allow`-Regel schaltet das nicht ab (confirm schlägt allow), nur die Config-Schalter `confirm_keyboard_each_time` / `confirm_window_close_each_time`.
- **Zielbindung:** Tastatureingaben gehen nur an das *aktive, inspizierte* Fenster; Prozess steht in der Ressource. Direkt vor dem Tippen/Klicken wird erneut geprüft: ist das Fenster inzwischen ein Terminal oder ein anderes (Fokus wechselte, während du den Prompt gelesen hast) oder hat sich die Bildschirmgröße geändert → `target_changed`/`blocked_target`, es passiert nichts.
- **Gezielte Fenstersteuerung (`window=<handle>`):** `keyboard` (press/hotkey/type) und `mouse` akzeptieren optional ein Zielfenster. Bei `mouse` sind `x`/`y` dann fenster-relativ (nicht mit `monitor` kombinierbar). Ablauf nach der Bestätigung: (1) Fenster existiert noch, gleiches Programm (Handle **und** PID/Prozess – ein wiederverwendetes Handle ist ein anderes Fenster), kein blockiertes Ziel, bei Mausaktionen unveränderte Geometrie; (2) Fokus über den Window-Provider; (3) Vordergrundfenster zurücklesen – es muss genau dieses Fenster sein; (4) bei Mausaktionen muss der Punkt nachweislich zu diesem Fenster gehören; (5) **vor jeder Eingabe** erneut prüfen – Text wird in 16-Zeichen-Stücken getippt, vor jedem Stück wird das aktive Fenster neu verifiziert (Wechsel mitten im Text stoppt die Eingabe; das gilt auch ohne `window`). Die Ressource bleibt `keyboard://text@<prozess>` bzw. `screen://monitor/i/x/y`, RED-Ziele (Terminals, Shells, Systemtools) bleiben auch bei explizitem Handle RED, bestätigt wird weiterhin jede Eingabe; der Prompt nennt Handle und Titel.
- **Windows-Vordergrundsperre:** `window action=focus` und die gezielte Eingabe nutzen unter Windows `SetForegroundWindow`, bei Verweigerung die dokumentierte Methode, kurz an die Eingabewarteschlange des aktuellen Vordergrund-Threads anzuhängen (`AttachThreadInput`, danach garantiert gelöst) – ohne Tasten- oder Mausereignisse zu injizieren. Das Ergebnis wird verifiziert; gelingt es nicht, gibt es `backend_error` und es wird nichts gesendet.
- **Der Controller verlangt selbst einen Grant:** `ComputerController.execute` läuft nur mit einem von der Engine ausgestellten, einmaligen `ExecutionGrant`, der zu *Tool, Aktion und Ressource* passt. Pläne sind HMAC-signiert (Tool, Aktion, Ressource, Level, Grund, Kontext, Ausführungsfunktion): verändert, handgebaut oder vertauscht → `not_authorized`. Es gibt kein `confirmed=`/`force=` – weder an Tools noch am Controller. Provider sind privat im Controller; `register_computer_tools` lehnt lockere Registries ab.
- **Notaus:** `/computer stop` (setzt per `/computer resume` fort), außerdem `pyautogui`-Fail-Safe: Mauszeiger in eine Bildschirmecke bricht jede Eingabe ab (`failsafe`). Zusätzlich Limit `max_actions_per_minute` (120) und serielle Ausführung (eine Maus, eine Tastatur).
- **Prompt-Ehrlichkeit:** Fenstertitel/Programmnamen werden von Steuer- und Formatzeichen bereinigt und in Anführungszeichen gesetzt (kein Fälschen von „Risiko: GREEN“-Zeilen); Secrets darin werden geschwärzt.

### Datenschutz
- **Screenshots** bleiben im Arbeitsspeicher (`screenshot_max_items`, begrenzt), werden nie automatisch gespeichert und nie gesendet (das Paket enthält keinen Netzwerkcode – per AST-Test). Tool-Ergebnisse, Logs und `repr` enthalten nur Metadaten (id, Größe, gekürzter Hash). Speichern ist `screen_save`: bestätigt, nur in erlaubte Ordner, nie überschreibend, Dateirechte 0600.
- **Getippter Text** steht nie in Ressource, Audit-Log, Logs, Fehlermeldungen oder `repr`. Im Audit steht `keyboard.type` auf `keyboard://text@notepad.exe`. Nur der Bestätigungsprompt zeigt eine Vorschau der ersten 40 Zeichen (Secrets geschwärzt; abschaltbar mit `show_text_preview = false`).
- Gestartete Programme erben **keine** Umgebungsvariablen mit `KEY/SECRET/TOKEN/PASSWORD` im Namen.

### Anwendungen starten – keine Shell
`app` löst einen **Alias aus `computer.apps`** zum echten Pfad (Symlinks aufgelöst, muss existieren und ausführbar sein) auf; dieser Pfad ist die Ressource, die die Engine sieht. Gestartet wird mit `subprocess.Popen([exe, *args], shell=False)`: Argumente sind eine Liste, jede Zeichenkette (`&& calc`, `$(id)`, `%PATH%`) kommt wörtlich als *ein* Argument an. Ein Alias-Wert ist ein Pfad, nie eine Kommandozeile. Argumente sind per Digest in der Ressource gebunden (eine Sitzungsfreigabe für `notepad` gilt nicht für `notepad <Datei>`). `allow_unlisted_apps = true` erlaubt zusätzlich absolute `.exe`-Pfade (weiter bestätigt, weiter gefiltert).

### Beobachten → handeln → prüfen
`screen action=screenshot` → Aktion → `screen action=screenshot` → `screen action=compare a=… b=…` liefert Anteil und Bereich der geänderten Pixel; `jarvis.computer.verify_change(before, after, expect_change=…)` ist der abhängigkeitsfreie Verifikationsschritt. Für einen späteren Vision-Agenten gibt es `ImageObserver.observe(screenshot, instruction)`: er bekommt das `Screenshot`-Objekt aus dem Speicher (nie einen Upload); automatisch ruft ihn nichts auf.

### UI-Automation (Modell, lesender Provider, lesendes Tool)
`jarvis/computer/uia.py` beschreibt den UI-Automation-Baum eines Fensters (`UiElement`: Name, Typ `ControlType`, AutomationId, Klasse, Rechteck `UiRect`, aktiviert, sichtbar, `is_password`, Wert, Kinder) und eine **rein lesende** Schnittstelle `UiTreeProvider` mit nur `describe(window_handle, limits)` und `find(window_handle, query, limits)`. Dazu der deterministische `FakeUiaProvider` (`providers/fake_uia.py`, fester Notepad- und Anmelde-Baum, zeichnet Aufrufe auf, kann einmal fehlschlagen). `ComputerBackend` hat dafür den optionalen Platz `ui` (Standard `None`; `capabilities()` bestehender Backends bleibt unverändert).
Das Modell erzwingt selbst: **Passwortfelder tragen nie einen Wert** (er wird beim Anlegen verworfen, kein `value` in `info()`, nie im `repr`); Tiefe (Standard 6, hart 12), Knotenzahl (200, hart 500) und Textlänge (200, hart 1000) sind begrenzt (`bound_tree`, Dokumentreihenfolge, nichts wird gesampelt, `truncated` meldet jede Kürzung); Steuerzeichen in Texten werden ersetzt; die Suche (`UiQuery`, UND-verknüpft, höchstens 50 Treffer) arbeitet nur im begrenzten Baum.
**Lesender Provider (Schritt `uia-provider-readonly`, Windows):** `providers/pywinauto_uia.py` (`PywinautoUiaProvider`) implementiert `UiTreeProvider` mit pywinauto 0.6.9 (UIA-Backend) und bietet nur **Fenster auflisten** (`list_windows`), **Baum beschreiben** (`describe`) und **Element finden** (`find`). Es gibt keine Eingabe, keinen Klick, keinen Fokuswechsel, keine Werte von Steuerelementen (nur das Passwort-Merkmal) und keine Prozesssteuerung fremder Programme (Strukturtest). Alle UIA-Aufrufe laufen in **einem eigenen Worker-Prozess** (`providers/uia_worker.py`), dessen Hauptthread die UIA-Verbindung besitzt; JARVIS importiert pywinauto nie selbst (COM-Threadmodus bleibt unberührt). Hängt der Worker, wird er nach `uia_call_timeout` beendet und beim nächsten Aufruf neu gestartet. Alles, was der Worker liefert, wird erneut geprüft und begrenzt (Tiefe, Knoten, Textlänge; Passwortfelder ohne Wert).

- **Optionales Extra, nur Windows:** `pip install -e ".[uia]"` (`pywinauto>=0.6.9,<0.7; sys_platform == 'win32'`). `dependencies = []` bleibt; `import jarvis` und die Linux-Suite brauchen die Bibliothek nicht, ein Fehlen ergibt eine klare Meldung („pywinauto is not installed … pip install -e .[uia]“) statt eines Absturzes. Das Extra `dev` enthält die Bibliothek unter Windows, damit der Windows-Testlauf das echte Fenster lesen kann.
- **Standard aus:** `computer.uia_enabled = false` (benötigt zusätzlich `computer.enabled`), `uia_max_calls_per_session = 200` (Sitzungsbudget, 1..10000, wird durch Notaus/Fortsetzen nicht zurückgesetzt), `uia_call_timeout = 20.0`. Der Notaus (`ComputerController.halt`) wird an den Provider weitergereicht: Aufrufe scheitern mit `failsafe`, der Worker wird beendet.
- **Lesendes Tool `ui` (Schritt `uia-tools-readonly`):** Mit `computer.uia_enabled = true` (und `computer.enabled`) registriert `build_computer` zusätzlich das Tool `ui` (`action=windows | tree | find`; Parameter `window`, `name_equals`, `name_contains`, `control_type`, `automation_id`, `enabled`, `visible`, `max_results`, `max_depth`, `max_nodes`). Ohne Provider gibt es das Tool nicht; die sechs bisherigen Werkzeuge und ihre Stufen bleiben unverändert. Es ist ein `ProtectedTool` mit `describe_action`; jeder Aufruf läuft über `ToolRegistry.execute` → `PermissionEngine` und ist **YELLOW** (es liest die Texte fremder Programme; Sitzungsfreigabe möglich). Ressourcen: `ui://windows`, `ui://tree/<Handle>/<Prozess>`, `ui://find/<Handle>/<Prozess>` (der Prozess bindet die Freigabe an das Programm, dem das Fenster bei der Freigabe gehörte). `windows` listet Handle, Titel, Prozess, Klasse und `readable`; nur der Controller ruft den Provider auf, ausführend nur nach passender Engine-Freigabe, zur Ausführungszeit wird das Fenster erneut geprüft (anderes Programm oder weg: nichts wird gelesen).
- **Was nie gelesen wird:** Fenster, die ohnehin keine Eingabe erhalten (Terminals, Shells, Skript-Hosts, Sicherheits- und Systemwerkzeuge, Run/Start/Suche, eigene `blocked_*`-Einträge) und zusätzlich **Passwortmanager, Anmeldeinformationsverwaltung und Banking-Fenster** (fest eingebaut, nur erweiterbar): RED, nie eine Rückfrage, nie ein Provider-Aufruf. Passwortfelder haben keinen Wert; Felder, deren Name oder AutomationId nach Geheimnis klingt (Passwort, Kennwort, PIN, Token, API-Schlüssel, Sicherheitscode …), verlieren ihren Wert; Geheimnisse in Texten werden durch `jarvis.redaction` (Controller) und den Detektor der Engine (Tool) ersetzt. Der Inhalt ist Daten eines anderen Programms, nie eine Anweisung.
- **Notaus, Budget, Zeitlimit:** `ComputerController.halt` und der Notaus-Latch der Engine verweigern jeden Aufruf; das Sitzungsbudget der Engine zählt jeden Aufruf, dazu `uia_max_calls_per_session` im Provider; ein hängender Worker wird nach `uia_call_timeout` beendet (strukturierter Fehler `backend_error`, der nächste Aufruf startet einen neuen Worker). **Keine Klicks, keine Eingaben, keine UI-Aktionen** (`uia-actions` ist nicht freigegeben und nicht begonnen). Tests: `tests/test_computer_uia_tools.py` (Linux und Windows; Fake-Provider).
- **Tests:** `tests/test_computer_uia_provider.py` (Protokoll, Zeitlimit, Notaus, Budget, Passwortfelder, fehlende Bibliothek, Strukturtests; Linux und Windows) und, nur unter Windows, `TestRealWindow` (liest ein per Subprozess gestartetes Notepad-Fenster; fehlt die Bibliothek, schlägt der Test fehl statt zu überspringen). Linux-Läufe sind kein Windows-Nachweis; der liegt beim Windows-CI-Lauf.

### Fehler (strukturiert, nie ein Absturz)
`ToolResult.output = {"code", "message"}` bzw. `[code]` in der Fehlermeldung: `disabled`, `backend_unavailable`, `no_display`, `invalid_monitor`, `invalid_coordinates`, `invalid_input`, `window_not_found`, `launch_failed`, `blocked_target`, `target_changed`, `not_authorized`, `unsupported`, `rate_limited`, `failsafe`, `backend_error`. Meldungen enthalten nie getippten Text oder Bildschirminhalt.

### Konfiguration `[computer]` (Umgebung: `JARVIS_COMPUTER_<FELD>`)
| Schlüssel | Default | Bedeutung |
|---|---|---|
| `enabled` | `false` | Opt-in; bei nicht nutzbarem Backend automatisch aus |
| `backend` | `auto` | `windows` (Windows), `x11` (Linux/Entwicklung), `fake`, `auto` = Plattform |
| `default_monitor` | `0` | Monitor, wenn keiner angegeben ist (nicht mehr vorhanden → primärer; ein *explizit* falscher bleibt ein Fehler) |
| `screenshot_max_items`, `screenshot_max_pixels` | `3`, 8K | Speicher-/Größenlimit |
| `max_text_length`, `type_interval`, `max_scroll`, `max_hotkey_keys`, `action_delay`, `max_actions_per_minute` | `500`, `0.02`, `20`, `4`, `0.05`, `120` | Grenzen |
| `show_text_preview`, `confirm_keyboard_each_time`, `confirm_window_close_each_time` | `true` | siehe oben |
| `apps` (TOML-Tabelle), `use_default_apps`, `allow_unlisted_apps` | `{}`, `true`, `false` | erlaubte Anwendungen |
| `blocked_processes`, `blocked_titles` | `["explorer.exe"]`, `[]` | zusätzliche Sperren (die eingebauten bleiben) |

Koordinaten werden **nie** auf den Bildschirm „geklemmt“: außerhalb ist ein Fehler. Es gibt keinen Schalter, der die Rückfragen, die eingebauten Sperren oder die Berechtigungsprüfung ausschaltet.

### Tests
Alle Automatiktests nutzen den `FakeBackend` (zeichnet jeden Aufruf auf, simuliert einen kleinen Desktop mit Pixeln, injiziert Fehler) und fingierte `pyautogui`/`mss`/Win32-Schnittstellen. Zusätzlich laufen 11 **echte** Tests (`tests/test_computer_x11_real.py`): echte Maus-/Tastaturereignisse (XTEST), echte Screenshots, echter Subprozess und eine echte X11-Testanwendung auf Xvfb, durch die produktive `build_core`-Verdrahtung. Ohne Xvfb/Bibliotheken werden sie übersprungen.
`apt install xvfb python3-tk && pip install -e ".[dev,computer]" && pytest tests/test_computer_x11_real.py`

### Bekannte Grenzen
- **Nur Windows-nah getestet, nicht auf Windows:** Der Windows-Pfad (`pyautogui`/`mss` + Win32-Fensterprovider über `ctypes`) ist gegen eine Fake-API getestet, wurde aber in dieser Umgebung nie auf einem echten Windows ausgeführt. Die Provider-Schnittstellen/Controller/Engine sind real auf X11 verifiziert. Bitte vor dem Einsatz auf Windows einmal `/run screen action=monitors`, `screenshot` und `app app=notepad` von Hand durchspielen.
- GUI-Automation kann alles, was der Nutzer per Oberfläche kann: Programme mit Befehlszeile oder Skriptfunktion (IDE-Terminals, Browser-Konsole, Office-Makros, Dateimanager) sind nicht pauschal gesperrt. Schutz: jede Tastatureingabe wird mit Ziel und Vorschau bestätigt; Standard-Shells, Run/Start/Suche und Explorer sind gesperrt; weitere Sperren über `blocked_*`. Argumente an freigegebene Programme interpretiert das Programm selbst (z. B. Browser mit Befehls-Flags) – Aliase mit Bedacht wählen; Argumente werden angezeigt und bestätigt.
- Die Zielprüfung ist eine Momentaufnahme (Fenster-Handles können wiederverwendet werden; minimale Zeitlücke zwischen Prüfung und Ereignis). Erhöhte (Administrator-)Fenster und der UAC-Dialog lassen sich unter Windows ohnehin nicht steuern.
- `pyautogui` tippt nur ASCII (+ Newline/Tab); anderes wird mit `unsupported` abgelehnt statt still verworfen. Mehrere Monitore mit unterschiedlicher Skalierung (DPI) sind nicht gesondert behandelt. Spiele/Remote-Desktops mit eigenem Eingabepfad können Eingaben ignorieren.
- Das Fenster-/Monitor-Wissen steht im `screen`-Ergebnis (Fenstertitel können vertraulich sein); `screen`-Beobachtungen sind GREEN und werden nur mit `security.audit_green = true` auditiert (Metadaten stehen immer im Log).
- Minimieren/Maximieren unter X11 ohne Fenstermanager (Xvfb) ist `unsupported`; X11 ist ein Entwicklungs-/Verifikationsbackend, nicht das Zielsystem.

## Browser Agent v1 (Phase 5)

Ein kleiner, bewusst **nicht autonomer** Browser-Agent: ein Tool-Aufruf = eine überprüfbare Aktion. Der Planner darf mehrere Schritte planen, aber jeder Schritt läuft einzeln durch ToolRegistry → PermissionEngine → `BrowserController` → `BrowserProvider`. Computer Control bleibt davon vollständig getrennt (eigener Controller, eigenes Paket, keine gegenseitigen Importe; der Browser steuert nie Maus oder Tastatur des PCs).

```
JARVIS Core → Planner/Tasks → browser-Tool → ToolRegistry → PermissionEngine → BrowserController → BrowserProvider (Playwright | Fake | …)
```

### Einrichtung (Windows)
```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m playwright install chromium      # oder: browser = "msedge" (Edge ist vorinstalliert, kein Download)
$env:JARVIS_BROWSER_ENABLED = "true"
.\.venv\Scripts\jarvis.exe
jarvis> /browser                                  # Status
jarvis> /run browser action=start                 # YELLOW: wird bestätigt
jarvis> /run browser action=goto url=https://example.com
jarvis> /run browser action=text                  # GREEN: sichtbarer Text (als „untrusted“ markiert)
jarvis> /run browser action=find query=Search     # liefert Element-IDs (e1, e2, …)
jarvis> /run browser action=fill element=e1 text="Wetter Berlin"
jarvis> /run browser action=submit element=e1
```
Ohne `playwright` startet JARVIS ganz normal; der Browser-Agent meldet dann „nicht verfügbar“ mit dem Installationshinweis (`/browser`). Kein Python-3.14-spezifischer Code; Playwright braucht dafür ein passendes `greenlet`-Wheel – falls die Installation scheitert, Playwright aktualisieren. Das Profil ist **immer neu und flüchtig** (kein Zugriff auf deine echten Browser-Profile, Cookies oder Passwörter).

### Aktionen des `browser`-Tools
| Gruppe | `action` | Level |
|---|---|---|
| Sitzung | `status` | GREEN |
| | `start`, `stop` | YELLOW |
| Seiten | `pages`, `active` | GREEN |
| | `new`, `activate`, `close`, `back`, `forward` | YELLOW |
| | `goto url=…`, `new url=…` | GREEN für `browser.trusted_hosts`, sonst YELLOW; RED für verbotene Adressen |
| | `reload` | GREEN auf vertrauenswürdigem Host, sonst YELLOW |
| Lesen | `info`, `text`, `links`, `forms`, `find [role=…] [query=…]` | GREEN |
| Elemente | `click`, `fill text=…`, `select value=…`, `check checked=true`, `submit` | YELLOW (RED bei Login/Zugangsdaten/verbotenem Ziel) |
| Dateien | `download path=…`, `upload path=…` | YELLOW, immer gefragt, Pfad über `PathGuard` |

Elemente werden **semantisch** gefunden (Rolle + zugänglicher Name aus `aria-label`, Label, Text, Placeholder …), nie über Bildschirmkoordinaten. `find|links|forms` liefern Element-IDs; nur diese IDs nehmen `click`/`fill`/… an – es gibt keine Selector-, XPath-, JavaScript- oder Koordinaten-Eingabe.

### Ressourcen (was Engine, Regeln und Audit sehen)
```
browser://session/<sid>                       Start/Stopp
browser://page/<sid>/<pid>@<host>             eine Seite (Lesen, Verlauf, Schließen)
browser://element/<sid>/<pid>/<eid>@<host>    ein Element (click, fill, …)
<host>                                        Navigation: Resource-Typ DOMAIN der Engine, also auch "*.example.com"-Regeln
<Pfad>                                        Download-Ziel / Upload-Quelle: Resource-Typ PATH → PathGuard
```
Policy-Beispiel: `resource_type = "other"`, `resources = ["browser://element/*@*.example.com"]`. Der getippte Text steht **nie** in einer Ressource.

### Sicherheitsmodell
- **Eine Tür:** `BrowserController.execute` läuft nur mit einem von der Engine ausgestellten, einmaligen `ExecutionGrant` für genau *dieses* Tool, *diese* Aktion und *diese* Ressource; Pläne sind HMAC-signiert (verändert, handgebaut oder von einem anderen Controller → `not_authorized`). Kein `confirmed=`/`force=`. Der Provider ist privat im Controller; `register_browser_tools` lehnt lockere Registries ab. AST-Tests stellen sicher, dass außerhalb des Controllers kein Provider-Aufruf, kein Playwright-Import (nur ein Modul, lazy), kein Shell-/subprocess-Aufruf, keine Cookie-/Storage-/Header-API und kein weiteres Skript außer dem festen Beschreibungs-Skript existiert.
- **RED (nicht konfigurierbar):** alle Schemata außer http(s) (`file:`, `javascript:`, `data:`, `chrome:`, `view-source:`, `ftp:`, `mailto:` …); URLs mit Zugangsdaten; Cloud-Metadaten-/Link-Local-Adressen; interne/private Adressen (`localhost`, `10.*`, `192.168.*`, `*.local`, einteilige Namen), es sei denn, du trägst den **exakten** Host in `browser.private_hosts_allowed` ein; `browser.blocked_hosts`; Login-Formulare (jede Aktion darin); Passwort-, Einmalcode- und Zahlungsfelder; Text, der wie ein Secret aussieht (API-Key, `password=…`), wird nie in eine Webseite getippt; Links/Formulare mit verbotenem Ziel; Datei-Auswahlfelder per `click`; ausführbare/Skript-Downloads (`.exe .msi .bat .cmd .ps1 .js .vbs .lnk .jar .sh …`, auch wenn der Server sie anbietet); Zugangsdaten-/Schlüsseldateien als Upload (`.env`, `id_rsa`, `*.pem`, `*.kdbx`, Cookies …). Eine Anmeldung muss der Benutzer selbst durchführen; JARVIS erkennt das Formular (`login_form_detected`) und stoppt.
- **Immer fragen:** Baseline-Regeln `browser-baseline-*` (sichtbar in `/permissions`) erzwingen die Rückfrage bei jedem `fill`, `download` und `upload`, ohne Sitzungsfreigabe (abschaltbar nur per Config).
- **Zielbindung und Elementidentität:** Jedes Element hat eine Referenz mit Sitzung, Seite, URL-Kontext (ohne Query/Fragment), Locator und einem Fingerabdruck aus Tag, Rolle, Name, Typ, id/name und Link-Ziel. Vor *jeder* Aktion – und noch einmal direkt vor dem Ausführen – wird geprüft: Seite existiert · richtige Sitzung · richtige Seite · URL noch kompatibel · Element existiert noch · gleiches logisches Element · (Berechtigung: einmaliger Grant). Bei Abweichung bricht die Aktion mit `stale_element`/`element_not_found`/`target_changed`/`session_mismatch`/`page_not_found` ab – es wird **nie** auf ein ähnliches Element ausgewichen. Nach einer Navigation sind alle Referenzen der alten Seite ungültig.
- **Navigation wird im Browser selbst erzwungen:** der Controller reicht dem Provider einen URL-Guard, der jede Anfrage (Navigation, Redirect, Subressource) prüft und verbotene abbricht; zusätzlich wird die End-URL nach jeder Aktion neu geprüft (Seite wird sonst auf `about:blank` verlassen). Popups werden als Seiten registriert (Limit `max_pages`, überzählige werden geschlossen).
- **Keine blinde Schleife:** Timeouts für Navigation und Aktionen, `max_actions_per_session` (Standard 300, danach `failsafe`), `max_actions_per_minute`, Notaus `/browser halt` bzw. `/browser resume`.
- **Downloads/Uploads:** Das `browser`-Profil nimmt nie von selbst Downloads an – ungefragte werden abgebrochen und gemeldet. `download path=…` schreibt erst in ein privates Temp-Verzeichnis und kopiert dann auf den von der Engine geprüften echten Pfad (`PathGuard`: nur erlaubte Verzeichnisse, nie überschreiben, kein Symlink am Ende, Rechte 0600, Größenlimit); heruntergeladene Dateien werden nie geöffnet oder ausgeführt. `upload path=…` wählt nur eine geprüfte, vorhandene Datei in einem `<input type=file>` aus.
- **Keine Zugangsdaten:** keine Passwortverwaltung, keine Cookie-/Token-/Header-/Storage-Funktion (nicht vorhanden, per AST-Test gesichert), frisches nicht persistentes Profil. Feldinhalte werden nie gelesen (nur `has_value`). URLs erscheinen in Prompts, Ergebnissen und Audit ohne Zugangsdaten, Query-Werte und Fragment. Getippter Text steht nur im Bestätigungsprompt (Secrets geschwärzt), nie in Audit, Logs, Fehlermeldungen oder `repr`.
- **Seiteninhalt ist Daten:** `text` ist als `untrusted_content` markiert; Titel/Namen werden von Steuer- und Formatzeichen bereinigt (kein Fälschen von Prompt-Zeilen). Eine Seite kann JARVIS also nichts „befehlen“ – jede Aktion braucht trotzdem die Bestätigung.

### Konfiguration `[browser]` (Umgebung: `JARVIS_BROWSER_<FELD>`)
`enabled=false`, `provider="playwright"` (`fake` für Tests), `browser="chromium"` (`chrome`, `msedge`), `executable_path=""`, `headless=false`, `navigation_timeout=15`, `action_timeout=5`, `max_pages=5`, `max_text_chars=20000`, `max_elements=100`, `max_actions_per_minute=60`, `max_actions_per_session=300`, `max_download_bytes=50000000`, `trusted_hosts=[]` (GREEN-Navigation; exakt oder `*.example.com`), `blocked_hosts=[]`, `private_hosts_allowed=[]` (exakte interne Hosts), `confirm_fill_each_time=true`, `confirm_file_transfer_each_time=true`. Es gibt keinen Schalter, der RED, Login-Schutz oder die Berechtigungsprüfung abschaltet; unbekannte Schlüssel werden abgelehnt.

### Tests
`tests/test_browser_basics.py` (Interfaces, URL-Policy, Ressourcen, Config, Factory, CLI), `test_browser_controller.py` (Tool + echte Engine + Fake-Provider: Level, Sitzungen/Seiten, Lesen, Interaktion, Elementidentität, Budgets, Downloads/Uploads), `test_browser_security.py` (Bypass-Inspektion, Leaks, Architektur), `test_browser_real.py` (echter Browser gegen eine lokale Testseite; skippt sauber ohne Playwright/Browser; `JARVIS_TEST_BROWSER=msedge` wählt den Browser). Unter Windows: `.\.venv\Scripts\python.exe -m pytest -q -rf`.

### Bekannte Grenzen (v1)
- Kein DNS-Abgleich: ein Hostname, der auf eine private Adresse zeigt, wird nicht erkannt (nur Literale und typische interne Namen). Der Browser läuft mit deinen Netzwerkrechten – nur vertrauenswürdige Hosts in `trusted_hosts` eintragen.
- Elemente werden über Dokumentreihenfolge + Fingerabdruck adressiert; erscheinen vor einem Element neue Elemente, gilt es bewusst als „stale“ und muss neu gelesen werden. Shadow-DOM/iframes werden in v1 nicht durchsucht.
- Download-Größe wird erst nach dem Empfang in das private Temp-Verzeichnis geprüft.
- Mehrere Sitzungen gleichzeitig gibt es nicht (eine Sitzung, mehrere Seiten). Kein Screenshot, kein Vision, kein autonomer Agentenloop (spätere Phasen).

## Coding Agent v1 (Phase 6)

Der Coding Agent führt einen **kontrollierten** Entwicklungszyklus aus – analysieren, lesen, ändern, testen, Fehler lesen, korrigieren, erneut testen, berichten – aber immer als einzelne, einzeln geprüfte Schritte. Es gibt keine Agentenschleife: der Planner/Core ruft das Tool Schritt für Schritt auf, jeder Schritt läuft durch ToolRegistry → PermissionEngine → `CodingController` → `CodingProvider`. Computer Control und Browser bleiben getrennte Module (keine gegenseitigen Importe, keine Kopplung).

```
Core → Planner/Tasks → coding-Tool → ToolRegistry → PermissionEngine → CodingController → CodingProvider (local | fake) → Dateisystem / Test-Runner
                                                                                         └→ LLM-Abstraktion des Cores (nur bei der bestätigten Aktion `plan`)
```

### Einrichtung
```powershell
$env:JARVIS_CODING_ENABLED = "true"                      # Standard: aus; keine zusätzliche Abhängigkeit (nur Standardbibliothek)
.\.venv\Scripts\jarvis.exe
jarvis> /run coding action=start workspace=C:\Users\ich\jarvis-workspace\mein-projekt    # YELLOW: Bestätigung
jarvis> /run coding action=info                         # Sprache, Framework, Test-Framework, wichtige Dateien
jarvis> /run coding action=search pattern=PermissionEngine glob=*.py
jarvis> /run coding action=read path=src/calc.py        # liefert content + sha256
jarvis> /run coding action=write path=src/calc.py mode=replace old_text="a - b" new_text="a + b"
jarvis> /run coding action=test                         # python -m pytest, bestätigt, ohne Shell
jarvis> /coding                                         # Status; /coding halt | resume | stop
```
Workspaces dürfen nur in `coding.workspace_roots` liegen (Standard: das JARVIS-Workspace-Verzeichnis) **und** müssen zusätzlich in `security.allowed_roots` liegen – zwei Mauern: Controller und PathGuard der Engine.

### Aktionen des `coding`-Tools
| Gruppe | `action` | Level |
|---|---|---|
| Sitzung | `status`, `stop` | GREEN |
| | `start workspace=…` | YELLOW (RED außerhalb der erlaubten Wurzeln) |
| Lesen | `info`, `list`, `read`, `search`, `changes`, `git sub=status\|diff\|log` | GREEN (RED für Secret-Dateien, `.git`-Interna) |
| Ändern | `write mode=create\|overwrite\|replace`, `delete` | YELLOW; `delete` immer gefragt; `write.jarvis` / `write.deps` / `delete.jarvis` immer einzeln gefragt |
| Prüfen | `test [runner=…] [args=…]` | YELLOW (Freigabe gilt nur für genau diesen Code-Stand) |
| Planen | `plan goal=… paths=a.py,b.py` | YELLOW, immer gefragt (sendet Auszüge an den LLM-Provider) |
| nicht als Aktion vorhanden | `halt`, `resume` | nur der Benutzer (`/coding halt`, `/coding resume`) |
| RED | `git commit\|push\|reset\|clean\|checkout …`, jedes andere Git-Kommando | immer abgelehnt und im Audit protokolliert |

### Ressourcen
Datei- und Verzeichnisaktionen nutzen den **PATH-Resource-Typ der Engine** (echter, aufgelöster Pfad): der vorhandene `PathGuard` (erlaubte Wurzeln, verbotene/geschützte Pfade, Symlinks, Groß-/Kleinschreibung) und normale Pfadregeln gelten direkt. Bestätigungsprompts und Kontext zeigen zusätzlich die lesbaren Namen `coding://workspace/<id>`, `coding://file/<workspace>/<pfad>`; `coding://session/<id>`, `coding://test/<session>/<runner>#<code-stand>` und `coding://llm/<session>` sind die Engine-Ressourcen der Sitzungs-, Test- und LLM-Aktionen. Ein Grant gilt für genau eine Datei bzw. einen Code-Stand – nie für „coding write“ allgemein.

### Änderungsmodell
`read` liefert `content` und `sha256`. `write` hat drei Modi: `create` (Datei darf nicht existieren), `replace` (`old_text` muss genau einmal vorkommen; CRLF-Dateien bleiben CRLF) und `overwrite` (verlangt `expected_sha256` aus dem `read`). Vor jeder Bestätigung zeigt JARVIS eine Zusammenfassung (Datei, Art, `+N / -M Zeilen`, neue Funktionen/Klassen, die ersten geänderten Zeilen – geschwärzt). Danach gilt: **Was bestätigt wurde, wird geschrieben – oder nichts.** Die Aktion wird nach der Bestätigung aus dem aktuellen Zustand neu aufgebaut und muss exakt dieselbe Änderung ergeben (Hash alt → neu), und der Provider ersetzt die Datei atomar *nur*, wenn ihr Inhalt noch den erwarteten Hash hat; sonst `ABORT: file_changed`, nichts wird überschrieben. Löschen ist genauso hash-geschützt (nur einzelne Dateien, keine Verzeichnisse). Geschrieben wird nie durch einen Symlink; Binär-/Programmdateitypen (`.exe .dll .so .pyc …`) werden nicht geschrieben. `FileChange` hält pro Datei nur Pfad, Art, Hashes und Zeilenzahlen – nie Inhalte.

### Workspace-Grenzen
Jeder Pfad wird als *relativ* geprüft, auf jeder Plattform gleich: `..`, absolute Pfade (POSIX, `C:\`, `\\server\share`, `\\?\`), `~`, `:` (Laufwerke, NTFS-Streams), Gerätenamen (`CON`, `NUL`, `COM1` …), Steuer-/Unsichtbare-Zeichen sowie Punkt/Leerzeichen am Ende werden abgelehnt. Danach wird der **echte Pfad** (Symlinks aufgelöst) komponentenweise gegen den Workspace geprüft (`/ws/proj-evil` liegt nicht in `/ws/proj`; unter Windows ohne Beachtung der Groß-/Kleinschreibung). Namensprüfungen (`.env`, `.git`) nutzen `casefold` und prüfen auch den aufgelösten Pfad, ein harmloser Link auf `.env` bleibt also geschützt. Vor jeder Aktion wird zusätzlich geprüft, dass der Workspace noch dasselbe Verzeichnis ist (nicht gelöscht, nicht durch einen Link ersetzt: `workspace_changed`, Sitzung `failed`).

### Test-Runner (kein Shell, keine beliebigen Befehle)
Erlaubt sind nur die Runner `pytest`, `python -m pytest`, `python -m unittest` (Standard) und `npm test` (nur wo `npm` eine echte Programmdatei ist – unter Windows ist es ein `.cmd`-Skript und wird *nicht* gestartet, damit nie ein Befehlsinterpreter beteiligt ist). `coding.test_commands` wählt nur unter diesen bekannten Runnern; ein anderer Eintrag wird abgelehnt. `python` bedeutet immer **diesen** Interpreter (`sys.executable`), nie eine PATH-Suche. Argumente sind eine Liste und kommen aus einer kleinen Allow-List (`-q -v -x -k <Ausdruck> -m <Ausdruck> --tb=… --maxfail=N` und workspace-relative Test-Pfade/Node-IDs; Plugins, Konfigurationsdateien, `--rootdir`, Ausgabedateien usw. sind gesperrt). Der Provider startet mit `shell=False`, Argumentliste, absolutem Programm (nie eine Shell, kein Skript-Host, keine `.bat/.cmd/.ps1`), bereinigter Umgebung (ohne `*KEY*/*TOKEN*/*SECRET*/*PASSWORD*`, `PYTHONPATH`, `PYTEST_ADDOPTS`, `GIT_CONFIG_*` …), ohne stdin, mit Zeitlimit (`coding.test_timeout`) und Ausgabelimit (`coding.max_output_bytes` pro Strom; bei Überschreitung wird der Prozess beendet). `TestResult` enthält Befehl, Exit-Code, `passed`, `timed_out`, `stdout`, `stderr` (getrennt), Dauer, Zusammenfassung und die fehlgeschlagenen Tests; Secrets in der Ausgabe werden geschwärzt. `/coding halt` beendet einen laufenden Testlauf sofort. Unter Windows läuft jeder gestartete Prozess in einem Job Object (vorhandenes Modul `jarvis.self_improvement.winjob`, nur in `bootstrap.py` verdrahtet): Timeout, Ausgabe-Flut und `halt`/`abort_running` beenden den **gesamten Prozessbaum**, auch verwaiste Enkelprozesse. Gelingt die Zuordnung zum Job nicht, bleibt der Fallback das Beenden des Wurzelprozesses. Tests: `tests/test_coding_process_tree.py` (Fake-Job auf allen Plattformen; Windows-Tests mit Kind-/Enkelprozessen werden unter Linux übersprungen – der Windows-Nachweis kommt aus dem CI-Windows-Lauf).
**Wichtig:** Tests führen Projektcode aus – auch von dir oder JARVIS geschriebenen. Deshalb wird jeder Lauf bestätigt, und die Sitzungsfreigabe gilt nur für den *aktuellen Code-Stand* (ändert sich eine Datei, wird neu gefragt). Es gibt keinen Sandbox-Schutz gegen bösartigen Testcode; arbeite nur in Projekten, denen du traust.

### Projektanalyse und Suche
`info` erkennt Python (`pyproject.toml`, `requirements.txt`, `setup.py`, `pytest.ini` …), JavaScript/Node.js (`package.json`), TypeScript (`tsconfig.json`/Abhängigkeit) und liefert `ProjectInfo(root, language, framework, test_framework, important_files, is_jarvis_workspace)`. `search` ist eine Textsuche (wörtlich, optional ohne Beachtung der Groß-/Kleinschreibung, `glob=*.py`) nur im Workspace: sie folgt keinen Links, überspringt `.git`, `node_modules`, `.venv`, `__pycache__` u. ä., Secret-Dateien, Binärdateien und zu große Dateien (mit Zähler `skipped`), begrenzt Treffer (`coding.max_search_results`), Dateianzahl und Zeilenlänge und schwärzt Treffer.

### Secrets
`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`, `id_rsa*`, `id_ed25519*`, `credentials*`, `secrets.*`, `.npmrc`, `.netrc`, `.ssh/`, `.aws/` … werden **nie** gelesen, durchsucht, geschrieben, gelöscht oder an den LLM gesendet (RED, `secret_detected`); `.env.example` o. ä. sind normale Dateien. In anderen Dateien erkannte Secrets (API-Keys, Tokens, `password=…`, private Schlüssel) werden in `read`, `search`, Git- und Testausgabe geschwärzt. Neuer Text, der ein Secret enthält, wird nie geschrieben (`secret_detected`); eine Datei, die Secrets enthält, wird nur per `mode=replace` geändert, sodass sie nie umgeschrieben werden. Weder Audit noch Logs noch Fehlermeldungen enthalten Dateiinhalte oder Ausgaben.

### Git (nur lesend)
`git status|diff|log` laufen ohne Pager, ohne Hooks, ohne `fsmonitor`/externe Diff-/Textconv-Programme, mit bereinigter Git-Umgebung und mit Ausschluss der Secret-Dateien aus dem Diff. `commit`, `push`, `reset --hard`, `clean`, `checkout -- .` und jedes andere Git-Kommando werden **nicht** ausgeführt, sondern als RED abgelehnt und protokolliert (strenger als das später vorgesehene „YELLOW mit Bestätigung“).

### JARVIS-Repository (Vorbereitung auf Selbstverbesserung)
Das Repository von JARVIS wird erkannt (`is_jarvis_workspace`). Lesen, Analysieren, Suchen und Tests sind wie überall möglich; **jede** Änderung und jedes Löschen dort läuft als `write.jarvis`/`delete.jarvis` mit Pflichtbestätigung ohne Sitzungsfreigabe (Baseline-Regel), ebenso Änderungen an Abhängigkeitsdateien in jedem Projekt (`write.deps`). Es gibt keine automatische Änderung, keinen Commit und keinen Push des eigenen Systems. Spätere Phasen (Sandbox, Benchmark, Versionierung, Rollback) können darauf aufbauen.

### LLM
Der Coding Agent hat keinen eigenen LLM-Client; die Aktion `plan` verwendet den `LLMProvider` des Cores (`LLMRequest`/`Message`), nur auf ausdrückliche, **immer bestätigte** Anfrage. Gesendet werden Ziel, Projektüberblick, die genannten (max. 5) Dateien und optional das letzte Testergebnis – lokal erkannt, geschwärzt, auf `coding.llm_context_chars` begrenzt; der Prompt nennt Anbieter („EXTERN“ außer `mock`), Dateien und Umfang. Die Antwort ist Modelltext (nicht vertrauenswürdig); es wird nichts davon automatisch angewendet. Standard bleibt: keine Projektdateien an den LLM.

### Sitzung, Budget, Notaus
Jeder Auftrag hat eine Sitzung (`id`, Workspace, `created_at`, `status` = `active|halted|completed|failed`, geänderte Dateien, Testläufe, Aktionszähler). `max_actions_per_session` (300; Lesen zählt mit) und `max_actions_per_minute` begrenzen Schleifen: bei Überschreitung `action_budget_exceeded`, die Sitzung ist `failed`, nur `stop` bleibt. `/coding halt` stoppt sofort (auch einen laufenden Test), `/coding resume` setzt fort, `/coding stop` beendet die Sitzung (Dateien bleiben unverändert). `halt`/`resume` sind absichtlich keine Tool-Aktionen: der Agent kann sich nicht selbst entsperren.

### Konfiguration `[coding]` (Umgebung: `JARVIS_CODING_<FELD>`)
`enabled=false`, `provider="local"` (`fake` für Tests), `workspace_roots=[]`, `max_actions_per_session=300`, `max_actions_per_minute=120`, `max_output_bytes=200000`, `max_file_size=1000000`, `max_search_results=100`, `max_list_entries=500`, `test_timeout=120`, `test_commands=["pytest","python -m pytest","python -m unittest"]`, `llm_context_chars=12000`, `confirm_delete_each_time=true`, `confirm_llm_each_time=true`. Es gibt keinen Schalter für RED, Secret-Schutz, Shell, Git-Schreiben oder die Berechtigungsprüfung; unbekannte Schlüssel werden abgelehnt.

### Tests
`tests/test_coding_basics.py` (Modelle, Pfadregeln, Policy/Runner, Projekterkennung, Diff, Provider-Vertrag, Config, Factory, CLI), `test_coding_controller.py` (Tool + echte Engine + Fake-Provider: Level, Sitzung, Lesen/Schreiben/Löschen, stale Dateien, Test-Läufe, Git, Budget, Halt, LLM-Plan), `test_coding_security.py` (AST-Scans und Bypass-Inspektion: Pfade, Symlinks, Secrets, Shell-Injection, Runner, Git, Leaks, geforgte Pläne), `test_coding_real.py` (echtes Projekt mit echtem pytest/unittest/git: erkennen → lesen → suchen → pytest schlägt fehl → Fehler erkennen → reparieren → erneut testen → melden; Timeout, Output-Flut, Umgebung, Symlinks, Windows-Pfadschreibweisen). Unter Windows: `.\.venv\Scripts\python.exe -m pytest tests/test_coding_real.py -vv`.

### Bekannte Grenzen (v1)
- Testcode läuft ohne Sandbox mit deinen Rechten (und Netzwerkzugriff); nur vertrauenswürdige Projekte, jeder Lauf wird bestätigt.
- Unter Windows beendet ein Timeout/Halt den Testprozess, nicht zwingend dessen Kindprozesse (kein Job-Object).
- Ein Wettlauf mit einem Angreifer, der lokal Verzeichnisse durch Links austauscht, ist zwischen Prüfung und Schreiben nicht vollständig auszuschließen; Symlink-Angriffe über die Zeit sind durch Neuprüfung und `O_NOFOLLOW` (neue Dateien) stark erschwert.
- Die Suche ist wörtlich (kein Regex), die Projekterkennung heuristisch; kein Ausführen von Linter/Build/Paketinstallation, kein Commit/Push, keine Selbstmodifikation (spätere Phasen).
- `npm test` ist unter Windows nicht verfügbar (siehe oben).

## Multi-Agent-Orchestrierung (Phase 7)

Eine reine **Koordinationsschicht** über den vorhandenen Agenten – kein Goal Engine, keine Selbstmodifikation, keine neue Fähigkeit. Der Orchestrator enthält keine Browser-, Computer- oder Coding-Logik; er verteilt strukturierte Aufgaben, überwacht sie und speichert Ergebnisse.

```
JARVIS Core ─ delegate() ─▶ AgentPlanner (wer ist geeignet?) ─▶ AgentOrchestrator ─▶ Agent ─▶ ToolGateway ─▶ ToolRegistry ─▶ PermissionEngine ─▶ Controller ─▶ Provider
                                                  │                        │
                                         AgentRegistry              AgentResult ─▶ nächster Agent (parent_results) / Core-TaskManager (Spiegel)
```

### Bausteine (`src/jarvis/agents/`)
| Modul | Inhalt |
|---|---|
| `models.py` | `AgentTask` (`task_id`, `agent_id`, `objective`, `input`, `required_capabilities`, `priority` 1–10, `parent_task_id`, `dependencies`, `timeout`, `metadata`, `memory_query`); Eingaben sind reine JSON-Daten, tief kopiert, begrenzt; `repr` ohne Inhalte |
| `result.py` | `AgentOutcome` (was ein Agent zurückgibt) und `AgentResult` (`task_id`, `agent_id`, `status`, `summary`, `output`, `error`, `error_code`, `started_at`, `finished_at`); Exceptions sind keine Schnittstelle: sie werden kontrolliert in ein Ergebnis überführt |
| `state.py` | Status-Automaten: Agent `AVAILABLE/BUSY/DISABLED/FAILED`, Task `PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED/BLOCKED`; ungültige Wechsel → `StateError` |
| `agent.py` | `Agent`-Interface (`id`, `name`, `description`, `capabilities`, `tool_names`, `status`, `perform()`, `cancel()`) |
| `registry.py` | `AgentRegistry` (register/unregister/get/list/has/find; Duplikate und ungültige Agenten werden abgelehnt; kein globaler Zustand) |
| `planner.py` | `AgentPlanner`: regelbasierte Wahl des **geeigneten** Agenten und der Capabilities (kein LLM, keine Zielplanung) |
| `context.py` | `AgentContext` (nur ausdrücklich Übergebenes) und `ToolGateway` (die einzige Tür nach außen) |
| `orchestrator.py` | `AgentOrchestrator`: `submit`, `start`, `cancel`, `get`, `list`, `describe`, `wait`, `run`, `wait_idle`, `set_enabled`, `reset_agent`, `shutdown` |
| `fake.py` | `FakeAgent` (success/failure/blocked/crash/cancelled/wait/hang) für Tests |
| `adapters/` | dünne Adapter `BrowserAgent`, `CodingAgent`, `ComputerAgent` und der Platzhalter `ResearchAgent` |
| `factory.py` | baut alles aus `[agents]`; `AgentsSubsystem.delegate()` ist der Einstiegspunkt für den Core |

### Capabilities
`browser.read`, `browser.interact`, `coding.read`, `coding.write`, `coding.test`, `coding.plan`, `computer.screen`, `computer.input`, `research.web`. Sie sagen nur, **welcher Agent grundsätzlich geeignet ist** und was *dieser Task* tun darf (Prinzip der minimalen Rechte: ein Task mit `coding.read` kann nicht schreiben, auch wenn der Coding Agent es könnte). Sie sind **keine Berechtigung**: jede Aktion fragt weiterhin die PermissionEngine.

### Agenten
| Agent | Werkzeuge | Capabilities | Schritte (`input.steps`) |
|---|---|---|---|
| `browser` | `browser` | `browser.read`, `browser.interact` | `{"action": "goto", "url": "…"}`, `{"action": "text"}`, … |
| `coding` | `coding` | `coding.read/write/test/plan` | `{"action": "test"}`, `{"action": "write", …}`, … (`halt`/`resume` gibt es nicht) |
| `computer` | `screen`, `screen_save`, `mouse`, `keyboard`, `window`, `app` | `computer.screen`, `computer.input` | `{"tool": "keyboard", "action": "type", "text": "…"}`, … |
| `research` | `browser` | `research.web` | **Platzhalter**: liest eine Seite (`input.url`) und gibt einen Auszug weiter; keine Suche, keine Zusammenfassung |

Ein Adapter führt die Schritte **nacheinander** je als *einen* Toolaufruf aus. Jeder Schritt muss (1) eine bekannte Aktion sein, (2) nur Capabilities benötigen, die der Task erlaubt, (3) nur dokumentierte Parameter nutzen. Der erste fehlgeschlagene Schritt beendet den Task: von der Engine verweigert → `BLOCKED` (`permission_denied`), Subsystem angehalten → `BLOCKED` (`halted`), sonst `FAILED`. Ein Agent, dessen Werkzeug nicht aktiviert ist (z. B. `browser.enabled = false`), wird `DISABLED` registriert.

### Orchestrator
`submit(task)` registriert (PENDING, nicht gestartet); Unmöglichkeiten (unbekannter/deaktivierter/fehlerhafter Agent, fehlende Capability, unbekannte Abhängigkeit, volle Queue) kommen als **`BLOCKED`-Ergebnis**, nicht als Exception. `start(task_id)` fordert die Ausführung an: der Task läuft, sobald seine Abhängigkeiten `SUCCEEDED` sind, sein Agent frei ist und ein Slot frei ist – bis dahin bleibt er `PENDING` (Reihenfolge: Priorität, dann Eingang). Ein Agent bearbeitet immer nur **einen** Task. `run(task)` = submit + start + (begrenzt) warten. Nichts pollt: gewartet wird über eine Condition, Timeouts laufen über einen Scheduler. Erledigte Tasks werden auf `max_history` begrenzt.
**Abhängigkeiten:** nur direkte (`dependencies=(…)`), ohne DAG-Engine. Ist eine Abhängigkeit nicht `SUCCEEDED` (FAILED/CANCELLED/BLOCKED), wird der Task – und transitiv alles danach – `BLOCKED(dependency_failed)` und **nicht** ausgeführt. Die Ergebnisse der Abhängigkeiten (und des `parent_task_id`) kommen als **Kopie** in `AgentContext.parent_results` beim nächsten Agenten an – strukturierte Daten, keine globalen Variablen, keine Dateien, kein Agent-Import.

### Nebenläufigkeit
`agents.max_concurrent` (Standard 3, 1–16) wird erzwungen: höchstens so viele Worker arbeiten gleichzeitig, der Rest bleibt `PENDING` (kein Thread pro wartendem Task, `max_queue` begrenzt die Warteschlange). `active_agents` zählt auch Arbeit, deren Task schon im Timeout ist, bis sie wirklich endet. Tests prüfen `aktiv ≤ Limit` zu jedem Zeitpunkt mit echten Threads (Limit 1, 2, 3, 30-Task-Burst) und Events statt Sleeps.

### Abbruch (Cancellation)
`cancel(task_id)`: `PENDING` → sofort `CANCELLED`. `RUNNING` → der Abbruch wird nur **angefordert** (Event + `Agent.cancel`); der Task wird erst `CANCELLED`, wenn der Agent wirklich zurückkehrt – der Orchestrator behauptet nie ein Ende, solange die Arbeit läuft. Hat der Agent in der Zwischenzeit regulär gewonnen, bleibt es `SUCCEEDED`. Agenten ohne Abbruch-Unterstützung melden das ehrlich (`accepted=False`). Die Adapter prüfen nach jedem Schritt; der Coding Agent stoppt einen **laufenden Testlauf** über das vorhandene Coding-`halt` (danach bleibt Coding angehalten, bis der Benutzer `/coding resume` sagt). Browser- und Computer-Aktionen sind kurz und durch die Tool-Timeouts begrenzt; sie enden nach dem aktuellen Schritt.

### Timeout
Jeder Task hat einen Timeout (`task.timeout` oder `agents.task_timeout_seconds`). Bei Ablauf wird der Task `FAILED(timeout)`, der Agent wird zum Abbruch aufgefordert – bleibt aber `BUSY` und der Slot belegt, bis die Arbeit tatsächlich aufhört; ein Spätergebnis wird verworfen. Ignoriert ein Agent den Abbruch länger als `cancel_grace_seconds`, wird er `FAILED` (bekommt nichts Neues) und erholt sich (`AVAILABLE`), sobald seine Arbeit zurückkehrt.

### Fehlerisolierung und Lebenszyklus
Ein Agent-Crash wird abgefangen: Task `FAILED(agent_crashed)` (nur Exception-Typ, geschwärzt), **dieser** Agent `FAILED`, alle anderen Agenten, die Registry und der Core laufen weiter. `FAILED → AVAILABLE` per `/agent reset <id>`; `AVAILABLE ↔ DISABLED` per `/agent disable|enable <id>`; ein deaktivierter Agent bekommt nichts mehr (auch nicht aus der Warteschlange).

### Sicherheitsgrenze
- Agenten halten **keinen** Controller, Provider, Core, keine Memory-Datenbank und keine Engine. Sie erhalten einen `AgentContext` mit genau: `task_id`, `objective`, `input` (Kopie), `allowed_capabilities`, `relevant_memory`, `parent_results`, `metadata`, `tools`.
- `ToolGateway` ist die einzige Tür: nur die vom Agenten deklarierten Werkzeuge, Umgehungsargumente (`confirmed`, `force`, `bypass`, `skip_permissions` …) werden abgelehnt, ein Budget je Task (`tool_call_limit`), Abbruchprüfung vor jedem Aufruf. Danach ist es ein gewöhnliches `ToolRegistry.execute` – die PermissionEngine entscheidet, fragt, auditiert. Die Schicht erzeugt, ändert oder erweitert **keine** Permissions.
- AST-/Source-Tests für `src/jarvis/agents/`: keine Module `subprocess`, `os`, `shutil`, `socket`, `requests`, `pyautogui`, `playwright`, `ctypes` …; kein `eval/exec/open/__import__`; kein `shell=`; kein Import von `jarvis.browser/coding/computer/permissions/llm`; `.execute(` nur im Gateway; kein Zugriff auf Controller/Provider/Engine; kein Modul-Singleton; kein `global`; keine Dateizugriffe. Browser, Coding, Computer, Permissions und Memory importieren die Schicht nicht.
- RED bleibt RED: Tests bestätigen für Agenten, dass `file:`-URLs, interne Adressen, `.env`, `git push/commit`, PowerShell-Fenster, Windows-Taste und `cmd` verweigert werden (BLOCKED, im Audit der Engine).
- Ergebnisse werden vor dem Speichern **geschwärzt** (`SecretDetector`) und in der Größe begrenzt; `repr` von Task/Ergebnis/Kontext enthält keine Inhalte; Logs enthalten nur IDs und Status.
- Memory nur auf ausdrückliche Anfrage (`memory_query`): höchstens 5 geschwärzte Einträge, nur lesend; Agentenergebnisse werden nie nebenbei im Memory gespeichert.

### Core-Integration
`bootstrap` baut das Subsystem `core.subsystems["agents"]` (nur wenn `agents.enabled`; der Core importiert die Schicht nicht). Jeder Agent-Task wird als **eigenes** Modell geführt und zusätzlich als Task im vorhandenen `TaskManager` gespiegelt (Beschreibung, Priorität, `required_agents`, Status PENDING/RUNNING/COMPLETED/FAILED/CANCELLED) – ohne beide Modelle zu vermischen. `AgentsSubsystem.delegate(objective, input, agent_id=None)` wählt (explizit oder per `AgentPlanner`) und führt **einen** Task aus; das Ergebnis ist immer ein `AgentResult`.

### CLI
`/agents` (Agenten + Status, aktiv/wartend), `/agent <id>` (Details), `/agenttasks` (aktive/letzte Tasks), `/agent halt <task_id>` (Abbruch), `/agent plan <Text>` (welcher Agent wäre geeignet), `/agent enable|disable|reset <id>`.

### Konfiguration `[agents]` (Umgebung: `JARVIS_AGENTS_<FELD>`)
`enabled=false`, `max_concurrent=3`, `task_timeout_seconds=300`, `max_queue=50`, `max_history=200`, `cancel_grace_seconds=5`, `tool_call_limit=200`, `max_output_chars=20000`. Ohne `enabled` startet JARVIS ganz normal; die Agenten setzen außerdem aktivierte Subsysteme (`browser`, `coding`, `computer`) voraus.

### Tests
`tests/test_agents_basics.py` (Modelle, Status, Registry, Planner, Kontext/Gateway, Config), `test_agents_orchestrator.py` (Lebenszyklus, Fehler, Abbruch, Timeout, Nebenläufigkeit, Abhängigkeiten, Kontext, TaskManager-Spiegel – deterministisch mit manuellem Scheduler/Executor und Events), `test_agents_integration.py` (Adapter gegen die echte PermissionEngine mit Fake-Providern), `test_agents_security.py` (Quell-/AST-Scans), `test_agents_core.py` (Bootstrap, CLI, `delegate`), `test_agents_real.py` (echte Threads + echtes pytest, echter Abbruch). Unter Windows: `.\.venv\Scripts\python.exe -m pytest tests/test_agents*.py -vv -rs`.

### Bekannte Grenzen (v1)
- Heuristischer Planner (Schlüsselwörter, Deutsch/Englisch); keine Zielplanung, keine Multi-Step-Planung, kein LLM – das gehört in die spätere Goal Engine. Der Core ruft `delegate()` noch nicht automatisch aus dem Dialog auf.
- Agenten führen **vorgegebene, strukturierte Schritte** aus (`input.steps`); sie entscheiden nicht selbst, was als Nächstes zu tun ist.
- Ein Python-Thread lässt sich nicht erzwungen beenden: Abbruch und Timeout sind kooperativ. Ein Agent, der nicht reagiert, blockiert seinen Slot, bis seine Arbeit endet (er wird `FAILED` markiert und bekommt nichts Neues).
- Der `ToolGateway` schützt vor Fehlern und versehentlichem Missbrauch durch Agenten-Code und wird durch AST-Tests abgesichert; er ist keine Sandbox gegen absichtlich feindlichen Python-Code im selben Prozess.
- `ResearchAgent` ist ein Platzhalter; Cancel stoppt den Coding-Testlauf über das globale Coding-`halt`, danach muss der Benutzer fortsetzen.
- Mehrere Orchestratoren/Prozesse teilen keinen Zustand; Ergebnisse sind nur im Speicher (nicht persistent).

## Goal Engine v1 (Phase 8)

Der Benutzer nennt ein **Ziel**; JARVIS macht daraus eine kontrollierte Folge von Schritten, lässt die **vorhandenen** Agenten sie ausführen, wertet die Ergebnisse aus und entscheidet: Ziel erreicht, nächster Schritt, blockiert, fehlgeschlagen oder Zeitüberschreitung. Die Goal Engine ist reine Koordination: sie fügt **keine Fähigkeit und keine Berechtigung** hinzu, ruft nie ein Tool, einen Provider oder das Betriebssystem direkt auf und ändert weder JARVIS noch installiert sie etwas (kein Self-Repair, keine Selbstmodifikation – das sind spätere Phasen).

```
Core ─▶ GoalEngine ─▶ GoalPlanner ─▶ AgentPlanner (wer?) ─▶ AgentOrchestrator ─▶ Agent ─▶ ToolGateway ─▶ ToolRegistry ─▶ PermissionEngine ─▶ Controller ─▶ Provider
        (Fortschritt)  (Schritte)                              (Ausführung)
```

| Verantwortung | Baustein |
|---|---|
| Ziele und Fortschritt verwalten | `GoalEngine` (`engine.py`) |
| Schritte erzeugen (deterministisch, ohne LLM) | `GoalPlanner` (`planner.py`) + Plan-Validierung (`validation.py`) |
| Agenten auswählen | bestehender `AgentPlanner` |
| Agenten ausführen, Concurrency, Timeouts, Abbruch | bestehender `AgentOrchestrator` |
| Ergebnisse bewerten, Retry/Blockade/Erfolg entscheiden | `GoalEvaluator` (`evaluator.py`, deterministisch) |
| Sicherheit durchsetzen | `PermissionEngine` (unverändert) |

### Modelle und Lebenszyklus
`Goal` (`goal_id`, `objective`, `status`, `priority`, `created_at`, `updated_at`, `timeout`, `max_steps`, `metadata`), `GoalStep` (`step_id`, `goal_id`, `objective`, `required_capabilities`, `assigned_agent`, `dependencies`, `status`, `result`, `attempts`, `max_attempts`, …), `GoalStepResult` (`step_id`, `status`, `summary`, `output`, `agent_id`, `task_id`, `duration`, `attempts`, `attempt_log`). Alle sind unveränderlich, begrenzt, serialisierbar und ohne Inhalte im `repr`; die Ausgabe wird geschwärzt.
Ziel: `PENDING → PLANNING → RUNNING ⇄ WAITING → SUCCEEDED | FAILED | BLOCKED | CANCELLED | TIMEOUT`. Schritt: `PENDING → RUNNING → SUCCEEDED | FAILED | BLOCKED | CANCELLED | TIMEOUT`. Endzustände sind endgültig, es gibt keinen Weg zurück (ein Retry bleibt `RUNNING` und zählt Versuche).

### Planung
Deterministische Vorlagen, getrieben von dem, was der Benutzer **ausdrücklich** angibt (URL im Ziel oder `url=…`, `workspace=…`, `edits`, `runner`, `read_paths`) – keine freie LLM-Schleife, keine erfundenen Fähigkeiten:
- **Webseite** (`Analysiere example.com und finde die Öffnungszeiten`): Research-Agent liest die Seite → Auswertung.
- **Coding** (`workspace` gegeben): Projekt analysieren → (nur mit ausdrücklich übergebenen `edits`) schreiben → Tests ausführen → Auswertung → Sitzung wieder beenden. „Behebe den Fehler“ **ohne** `edits` wird nicht erfunden, sondern endet `BLOCKED`.
- **Bildschirm** („Zeige die Fenster“): nur lesend (`computer.screen`). Maus/Tastatur-Ziele werden in v1 nicht automatisch geplant.
Nicht planbare oder mehrdeutige Ziele enden ehrlich `BLOCKED` mit Begründung.

### Prüfung vor der Ausführung
Ein Plan wird **vollständig** geprüft, bevor der erste Schritt startet (Goal-ID, doppelte/unbekannte Schritt-IDs, unbekannte Agenten/Fähigkeiten, Zyklen, max. Schritte (hart 50), max. Tiefe (20), Timeouts, Versuche, verbotene Schlüssel wie `confirmed/force/bypass/skip_permissions`, ungültige URLs/Schritt-Eingaben). Ein ungültiger Plan wird nie teilweise ausgeführt.

### Ausführung und Auswertung
`PLAN → STEP → RESULT → EVALUATE → NEXT` mit harten Grenzen (`max_steps`, `max_attempts_per_step`, `goal_timeout`, `step_timeout`). Unabhängige bereite Schritte werden gemeinsam an den Orchestrator übergeben; **er** entscheidet über Parallelität (keine zweite Parallelisierungslogik, kein Polling, kein eigener Scheduler – die Engine wartet auf die Condition des Orchestrators). Ein Schritt läuft erst nach erfolgreichen Abhängigkeiten; scheitert/blockiert/bricht eine Abhängigkeit ab, wird der Folgeschritt `BLOCKED` (keine Umgehung). Nach einem Fehler startet kein neuer Schritt mehr (Fail-fast); laufende werden abgewartet.
**Retries** nur bei vorübergehenden Fehlern (Timeout, Agentenabsturz, Provider-Fehler) und solange Versuche übrig sind; **nie** bei verweigerter Berechtigung (RED/abgelehnt), ungültigem Plan/Input, unbekanntem Agenten oder Fähigkeit. Jeder Versuch steht im `attempt_log` des Ergebnisses.
Der `GoalEvaluator` erklärt **kein** Ziel für erreicht, wenn ein Schritt eine Fehlermeldung meldet (z. B. Testlauf `passed=false`) oder nichts geliefert hat.

### Abbruch und Timeout
`cancel(goal_id)`: `PENDING` → sofort `CANCELLED`; laufend → Abbruch wird bei den Agenten angefordert (deren eigener Cancel-Mechanismus, z. B. Stopp des Testprozesses) und das Ziel wird `CANCELLED`, sobald das behandelt ist. Beendete Ziele bleiben unverändert. Reagiert ein Agent nicht, steht das als Warnung im Ergebnis – es wird nie behauptet, er sei gestoppt. Das Ziel-Timeout ist unabhängig vom Schritt-Timeout (der Orchestrator setzt dieses durch); nach Ablauf werden laufende Agenten über den bestehenden Cancel-Weg angehalten, das Ziel endet `TIMEOUT`.

### Kontrolliertes Replanning (Phase 14, optional)
Mit `goals.replanning = true` **und** einem vorhandenen LLM-Provider (derselbe, den der Core benutzt – es wird kein zweiter erzeugt) darf die Goal Engine nach einem **retryfähigen** Fehler (`timeout`, `agent_crashed`, `executor_failed`, `queue_full`, `step_failed`; nachdem die Retries des Schritts aufgebraucht sind) einen **alternativen Plan** anfordern – höchstens **2 zusätzliche Planungsversuche je Goal** (auch abgelehnte zählen), innerhalb des Goal-Timeouts. Kein Replanning bei Berechtigungsfehlern/BLOCKED, fatalen oder unbekannten Fehlercodes, Abbruch, Timeout oder fehlgeschlagener Auswertung.
- **Das Modell bekommt:** Ziel, bisherigen Plan, fehlgeschlagenen Schritt mit Fehlercode und geschwärzter, begrenzter Fehlermeldung, kurze Zusammenfassungen früherer Ergebnisse (keine Ausgaben), erlaubte Fähigkeiten und Limits – als Daten, nicht als Anweisungen. Antwort: **ein striktes JSON-Objekt**.
- **Das Modell darf nicht:** Agenten, Tools oder Berechtigungen nennen (Agenten wählt der `AgentPlanner`), Fähigkeiten hinzufügen (nur die, die das Goal schon nutzt), Eingaben für Schritte schreiben, die lesen/ändern/Code ausführen (dort nur `input_from` = unveränderte Wiederverwendung einer bisherigen Eingabe), neue URLs einführen (nur Umordnen vorhandener), offene Arbeit weglassen oder die Auswertung am Ende entfernen.
- **Prüfung:** jeder Kandidat durchläuft Schlüssel-/Fähigkeits-/Abhängigkeitsprüfung, danach `validate_plan` (Zyklen, Duplikate, Schritt-/Tiefenlimits, Timeouts, Versuche, verbotene Schlüssel); ein **strukturell identischer** Plan (Agent, Fähigkeiten, Abhängigkeiten, Eingaben) wird abgelehnt. Nicht gültig ⇒ Ziel endet wie ohne Replanning (`FAILED`), Grund in den Hinweisen.
- **Ablauf/Audit:** der alte Plan bleibt mit allen Ergebnissen im Ergebnis stehen (offene Schritte → `BLOCKED/replaced_by_replan`); der neue Plan trägt die Schritt-IDs `r<n>-s<i>`; Cleanup des alten Plans läuft **vor** dem neuen; das Ziel bleibt `RUNNING` (kein Rückweg nach `PLANNING`); `GoalResult.replans` und die Hinweise zeigen angenommene/abgelehnte Versuche.
- **Datenschutz:** das Ziel und geschwärzte Fehlertexte gehen an den Provider – deshalb standardmäßig **aus**.

### Kontext und Memory
`GoalContext` enthält nur, was der Benutzer ausdrücklich freigibt (`explicit_user_context`: nur bekannte Schlüssel, reine Daten, begrenzt, ohne Bypass-Schlüssel) und die Ergebnisse dieses Ziels. Keine Verbindung zum globalen Memory; Ziele, Schritt- und Ergebnisdaten werden **nicht** automatisch gespeichert. Logs enthalten nur IDs und Status – keine Ziele, Eingaben, Ausgaben oder Texte.

### Core-Integration und CLI
`bootstrap` baut `core.subsystems["goals"]` (opt-in, braucht `agents.enabled`; der Core importiert die Schicht nicht). Der Core bietet `create_goal()`, `run_goal()`, `cancel_goal()`, `get_goal()`, `list_goals()`. Aus normalem Chat entstehen **keine** Ziele; nur ausdrücklich (`/goal` oder Core-Aufruf).
`/goals` · `/goal <Ziel> [url=… workspace="…" runner=… read_paths=a,b]` · `/goal status <id>` · `/goal steps <id>` · `/goal cancel <id>`. Beispiele:
```
/goal Analysiere example.com und finde die Öffnungszeiten
/goal Prüfe das Projekt mit den Tests workspace="C:\Users\ich\arbeit\projekt" runner=pytest
```
Die CLI umgeht keine Prüfung: jede Bestätigung fragt weiterhin die PermissionEngine (ohne Rückfrage-Möglichkeit endet ein Ziel `BLOCKED`). `Strg+C` während `/goal …` bricht das Ziel ab.

### Konfiguration `[goals]` (Umgebung: `JARVIS_GOALS_<FELD>`)
`enabled=false`, `max_steps=20` (hart 50), `max_attempts_per_step=2` (hart 5), `goal_timeout_seconds=1800`, `step_timeout_seconds=300`, `max_active_goals=3`, `max_history=100`, `replanning=false`. Keine unbegrenzten Werte.

### Tests
`tests/test_goals_models.py` (Modelle, Status, Kontext, Policy), `test_goals_planner.py` (Planer, Plan-Validierung, Evaluator), `test_goals_engine.py` (Ausführung, Abhängigkeiten, Retry, Abbruch, Timeout, Loop-Sicherheit – deterministisch über Events/Fake-Agenten), `test_goals_integration.py` (komplette Kette gegen die echte PermissionEngine, Config, Bootstrap, Core, CLI), `test_goals_security.py` (AST-/Quellscans, Invarianten), `test_goals_real.py` (echte Threads, echter Orchestrator, echtes pytest, echter Abbruch/Timeout). Unter Windows: `.\.venv\Scripts\python.exe -m pytest tests/test_goals*.py -vv -rs`.

### Bekannte Grenzen (v1)
- Planer ist heuristisch und kennt drei Vorlagen (Webseite lesen, Projekt prüfen/ändern/testen, Bildschirm ansehen); keine freie Zielzerlegung, kein LLM. Neue Ziele brauchen neue Vorlagen.
- Code wird **nicht** selbst geschrieben: Änderungen nur über ausdrücklich übergebene `edits`.
- Ein Coding-Ziel braucht, dass noch keine Coding-Sitzung läuft (sonst scheitert `start`); der Browser-Pfad nutzt den selbstaufräumenden Research-Agenten.
- Abbruch/Timeout sind kooperativ (siehe Phase 7); ein nicht reagierender Agent bleibt mit Warnung zurück.
- Ziele und Ergebnisse liegen nur im Speicher (nicht persistent); es gibt keine automatische Zielerkennung im Chat.
- Nicht enthalten (spätere Phasen, ausdrücklich nicht begonnen): Self-Repair, Selbstmodifikation, automatische Installation von Fähigkeiten, Zugangsdaten-Verwaltung, autonome Zahlungen/Verträge/externe Kommunikation.

## Self-Testing / Self-Repair v1 (Phase 9)

JARVIS kann seine Arbeit **testen**, einen Fehler **erkennen**, eine **begrenzte Reparatur** über die bestehenden sicheren Coding-/Agent-Strukturen durchführen lassen und anschließend **belegen**, ob sie funktioniert. Das ist ausdrücklich **kein** Self-Improvement: nichts am JARVIS-Kern, an Permissions, Konfiguration oder Abhängigkeiten wird verändert; es wird nur in dem Workspace gearbeitet, den du im Befehl nennst.

```
Core ─▶ RepairEngine ─▶ DiagnosisEngine · RepairPlanner ─▶ AgentPlanner ─▶ AgentOrchestrator ─▶ Coding Agent ─▶ ToolGateway ─▶ ToolRegistry ─▶ PermissionEngine ─▶ CodingController ─▶ Dateisystem / Test-Runner
```
Die Schicht (`src/jarvis/self_repair/`) öffnet **keine** Datei, startet **keinen** Prozess und trifft **keine** Berechtigungsentscheidung – jeder Schritt (`start`, `test`, `write`, `changes`, `stop`) ist ein Task für den Coding-Agent, und die PermissionEngine fragt wie gewohnt. Kein zweiter Orchestrator, kein eigener Scheduler.

### Ablauf
```
Baseline-Test (ganze Suite) ─▶ Diagnose ─▶ Repair-Plan ─▶ Reparatur (Coding-Agent, YELLOW) ─▶ gezielter Re-Test ─▶ Regression ─▶ Bewertung ─▶ SUCCEEDED / FAILED / BLOCKED
```
- **Test-only** (`/repair Teste das aktuelle Projekt …`): nur Test, Ergebnis `SUCCEEDED` (grün) oder `FAILED` (Tests rot) – nichts wird verändert.
- **Reparatur** (Ziel enthält „behebe/repariere/fix …" oder `candidates` übergeben): sind die Tests schon grün, wird nichts geändert (`SUCCEEDED`, „nothing to repair"); der Ausgangsfehler wird nie als eigener Reparaturerfolg ausgegeben.
- **Goldene Regel:** Erfolg nur, wenn *gezielter Test PASS* **und** *Regression PASS* **und** *keine Policy verletzt* **und** *keine unerlaubte Datei geändert*. Schlägt der gezielte Test fehl, läuft keine Regression; schlägt die Regression fehl, ist der Lauf `FAILED` (mit Hinweis, wie viele der Fehler schon vor der Reparatur bestanden).
- **Diff-Kontrolle:** nach jeder Reparatur wird die `changes`-Liste der Sitzung gegen die Zieldateien des Plans geprüft; eine fremde Datei → `BLOCKED`, nichts wird akzeptiert (es gibt **kein** automatisches Zurückrollen – der Hinweis nennt die Dateien).
- **Limits gegen Endlosschleifen:** `max_attempts` (Standard 3, hart 5); dieselbe Reparatur zweimal vorgeschlagen → `FAILED`; Reparatur ändert nichts → `FAILED`; Timeout für den ganzen Lauf (`repair_timeout_seconds`, hart ≤ 3600).
- **Retries:** nur ein zusätzlicher Versuch bei vorübergehenden Fehlern von Lese-/Test-Tasks (sichtbar als Hinweis); Schreib-Tasks und verweigerte Berechtigungen werden nie wiederholt.

### Diagnose (deterministisch, ohne LLM)
`SYNTAX_ERROR`, `IMPORT_ERROR`, `ASSERTION_FAILURE`, `MISSING_FILE`, `TEST_FAILURE`, `TIMEOUT`, `ENVIRONMENT_ERROR`, `UNKNOWN`. Eine Kategorie wird nur genannt, wenn die (begrenzte, geschwärzte) Ausgabe sie belegt. `TIMEOUT`, `ENVIRONMENT_ERROR` und `UNKNOWN` werden **nicht** automatisch repariert → `BLOCKED`.

### Repair-Plan und Reparatur-Vorschläge
Der Plan enthält `objective`, `target_files`, `target_tests`, `allowed_capabilities` (nur `coding.read/write/test`) und `reason`. **v1 schreibt keinen Fix selbst:** die Änderungen kommen aus ausdrücklich übergebenen `candidates` (ein Kandidat pro Versuch, jeweils `{"edits": [{path, mode, old_text, new_text | content}], "target_files": [...]}`); ohne Kandidat endet der Lauf ehrlich `BLOCKED` („no repair proposal"). Eine spätere Phase kann einen intelligenteren `Proposer` einstecken, ohne an den Sicherheitsgrenzen etwas zu ändern.
Nie als Ziel erlaubt (→ `BLOCKED`, bevor irgendetwas geschrieben wird): `.env*`, `*.pem`, `*.key`, `credentials*`, `secrets*`, `id_rsa*` u. ä.; Pfade außerhalb des Workspace (`..`, absolut, Laufwerke, UNC); `.git`, `.github`, `permissions/`, `security/`, Umgebungen; Abhängigkeits-/Konfigurationsdateien (`pyproject.toml`, `setup.py`, `requirements*.txt`, `package.json` …); **Tests** (kein „Test schwächen, bis er grün ist"); alles außer vorhandenen `.py`-Dateien. Das JARVIS-Repository selbst ist kein Reparaturziel. Zusätzlich gelten weiter PathGuard, Workspace-Grenzen und Symlink-Prüfung des Coding-Controllers.

### Berechtigungen
Jede Reparatur ist mindestens YELLOW und wird von der PermissionEngine beantwortet – nie von der Self-Repair-Schicht. Es gibt keine Parameter wie `confirmed/approval/force/bypass/skip_permissions/unsafe/grant` (Kontext, Kandidaten und Schritte mit solchen Schlüsseln werden abgelehnt). Wird eine Aktion verweigert: `BLOCKED`, kein Retry, keine Umgehung. Kein Git (weder commit noch push), keine Paketinstallation, keine Shell.

### Abbruch und Timeout
`cancel(run_id)`: `PENDING` → sofort `CANCELLED`; laufend → bestehender Agent-/Coding-Abbruch (der laufende Testprozess wird über das Coding-`halt` gestoppt), danach `CANCELLED`. Reagiert ein Agent nicht, steht das als Hinweis im Ergebnis – es wird nie behauptet, er sei gestoppt. Nach Abbruch/Timeout bleibt die Coding-Sitzung offen (Hinweis im Ergebnis); sonst schließt der Lauf die Sitzung, die er selbst gestartet hat. Eine bereits laufende Benutzer-Sitzung wird nicht übernommen oder beendet.

### Datenschutz
Ausgaben und Zusammenfassungen sind begrenzt (Test-Ausgabe ≤ 3000 Zeichen, Fehlerliste ≤ 50) und geschwärzt; `repr()` und Logs enthalten nur IDs und Status. Es wird **nichts** automatisch im Langzeit-Memory gespeichert.

### Core-Integration und CLI
`bootstrap` baut `core.subsystems["self_repair"]` (opt-in; braucht `agents.enabled` und `coding.enabled`; der Core importiert die Schicht nicht). Core: `create_repair()`, `run_repair()`, `cancel_repair()`, `get_repair()`, `list_repairs()`. Normaler Chat startet nie einen Lauf. Die Goal Engine kann den Core-Aufruf später nutzen; es gibt keine zweite Goal Engine.
```
/repair                                  Übersicht der Läufe
/repair status [id]                      ID, Status, Phase, Versuche, Zusammenfassung
/repair attempts <id>                    Versuche mit Diagnose, gezieltem Test, Regression, Dateien
/repair cancel <id>
/repair Teste das aktuelle Projekt workspace="C:\Users\ich\projekt" [tests=tests/test_x.py] [runner=pytest]
/repair Behebe den Fehler in calc.py workspace="C:\Users\ich\projekt" candidates='[{"edits":[{"path":"calc.py","mode":"replace","old_text":"a - b","new_text":"a + b"}]}]'
```
`Strg+C` während eines Laufs bricht ihn ab.

### Konfiguration `[self_repair]` (Umgebung: `JARVIS_SELF_REPAIR_<FELD>`)
`enabled=false`, `max_attempts=3` (hart 5), `repair_timeout_seconds=900` (hart 3600), `step_timeout_seconds=300`, `max_active_repairs=1`, `max_history=50`.

### Tests
`tests/test_self_repair_units.py` (Modelle, Status, Policy, Kontext, Diagnose, Planer, Evaluator, Tester), `test_self_repair_engine.py` (alle Pfade mit dem skriptbaren `FakeCodingAgent`: Erfolg, transienter/permanenter Fehler, Berechtigung verweigert, Timeout, Abbruch, Absturz, unerwartete Dateiänderung), `test_self_repair_integration.py` (gegen die echte PermissionEngine, Config, Bootstrap, Core, CLI), `test_self_repair_security.py` (AST-/Quellscans, Invarianten), `test_self_repair_real.py` (echte Threads, echtes pytest, echte Dateien, echter Abbruch/Timeout, CRLF, Windows-Pfade). Unter Windows: `.\.venv\Scripts\python.exe -m pytest tests/test_self_repair_units.py tests/test_self_repair_engine.py tests/test_self_repair_integration.py tests/test_self_repair_security.py tests/test_self_repair_real.py -vv -rs`.

### Bekannte Grenzen (v1)
- Schreibt **keinen** Fix selbst: Reparaturen nur aus übergebenen Kandidaten; keine LLM-Anbindung, keine Code-Generierung.
- Nur Python-Quelldateien, nur vorhandene Dateien, nur `pytest`/`unittest`; keine Tests, Konfiguration, Abhängigkeiten, Secrets, Git.
- Kein automatisches Zurückrollen nach einer verworfenen Änderung; das Ergebnis nennt die geänderten Dateien.
- Läuft nur im ausdrücklich genannten Workspace und nur, wenn dort keine andere Coding-Sitzung läuft; das JARVIS-Repository ist ausgenommen.
- Abbruch/Timeout sind kooperativ (siehe Phase 7); Läufe liegen nur im Speicher.
- Nicht enthalten (spätere Phasen): Self-Improvement/Selbstmodifikation, autonome Hintergrund-Reparatur, Git commit/push, Paketinstallation, Credentials, Remote-Ausführung.

## Self-Improvement (Phase 15) – deaktivierter Vorschlagsworkflow

**Stand: Vorschläge ja, Codeausführung nein.** JARVIS kann aus tatsächlich vorhandenen Daten (beendete Ziele und Replans der Goal Engine, Reparaturläufe, Audit-Log) wiederkehrende Probleme erkennen, **Verbesserungsvorschläge** speichern und ihren Status führen. Vorgeschlagener Code wird in dieser Version **weder vorbereitet noch importiert, ausgeführt, getestet, zusammengeführt oder aktiviert** – es gibt dafür keinen Schalter. Der Grund steht unten unter „Warum keine Ausführung“. Alles ist standardmäßig **aus**.

```
Aktiv:   DETECTED ─▶ PROPOSED ─▶ (REJECTED)                    Analyse · Vorschlag · signierter Speicher · Statusführung · /improve list|show|analyze|propose|reject
Gesperrt (ExecutionDisabled): PREPARED ─▶ TESTED ─▶ READY_FOR_APPROVAL ─▶ APPROVED ─▶ ACTIVATED ─▶ ROLLED_BACK
```

Paket `src/jarvis/self_improvement/`. Wiederverwendet werden Goal-/Repair-Engine (nur lesend), `AuditLogger`, `SecretDetector`, die LLM-Abstraktion (`complete_text`) und der `ConfirmationProvider` der PermissionEngine. Der Core und die Sicherheitskomponenten wurden nicht verändert (einzige Berührung: ein zusätzlicher Audit-Ereignistyp `improvement`).

### Konfiguration `[self_improvement]` (Umgebung `JARVIS_SELF_IMPROVEMENT_<FELD>`)
`enabled=false`, `use_llm=false`, `repo_path=""`, `allow_prepare=false`, `allow_activation=false`, `data_dir`, `key_path`. **`repo_path`, `allow_prepare` und `allow_activation` sind reserviert: jeder andere Wert wird beim Start abgelehnt** (`ConfigError`), auch per TOML. Beim Start wird (fail closed) geprüft, dass `data_dir` und der HMAC-Schlüssel **außerhalb** von `security.allowed_roots`, `coding.workspace_roots`, Workspace und Log-Verzeichnis liegen und der Schlüssel nicht im `data_dir`; sonst bleibt das Subsystem deaktiviert. `PermissionEngine`/`PathGuard` wurden dafür nicht verändert.

### Was implementiert und durch Tests belegt ist
| Bereich | Verhalten | Belegt durch |
|---|---|---|
| Standard & Sperre | alles aus; `prepare/test/activate/rollback` → `ExecutionDisabled`, bevor irgendetwas geschieht; keine Prozesse (Test ersetzt `subprocess.Popen` durch einen Fehler); `ExecutionGuard` hat keinen Produktions-Unlock, die Factory baut weder Workspace noch Pipeline-Ausführung; die verändernden Methoden von `GitWorkspace` (`create_worktree`, `apply_and_commit`, `discard`, `fast_forward`, `revert`) fragen den Guard selbst (Default: gesperrt), ein direkter Aufruf umgeht die Sperre also nicht | `test_self_improvement_workflow.py`, `…_security.py` |
| Analyse | nur echte Datensätze, Beleg mit IDs und Anzahl, kein Beleg ⇒ kein Vorschlag, defekte Quellen werden gemeldet; Logtexte werden redigiert und ändern nie einen Status | `…_analysis.py` |
| Speicher (V4) | HMAC-SHA256 über die ganze Datei, geprüft bei **jedem** Lesen; Manipulation von Status/Freigabe/Pfaden/Hashes, falscher Schlüssel, Abschneiden, Rollback (innerhalb eines Prozesses) ⇒ `IntegrityError`, Datei bleibt unverändert (`*.tampered`); Compare-and-swap je Vorschlag (`rev`) + Dateisperre ⇒ keine Lost Updates (Threads **und** Prozesse getestet) | `…_store.py` |
| Allow-List (V6) | änderbar sind nur ausdrücklich gelistete Dateien (`policy.ALLOWED_TARGETS`, aktuell 11); alles andere – auch Schreibweisen mit Groß-/Kleinschreibung, `..`, Backslash, `~`/8.3, Streams, Unicode – wird abgelehnt; zusätzlich Never-Liste und Namensregeln | `…_policy.py` |
| Diff-Prüfung (V7) | geänderte Dateien aus `git diff-tree --raw` (Status, Modi, Blob-IDs), Blobs aus der Objektdatenbank mit SHA-1-Prüfung, UTF-8/NUL/Größe, AST-Prüfung des **gesamten** neuen Moduls gegen das alte; `++`-Zeilen, `-diff`/binary-Attribute, Modus-/Symlink-/Rename-/Add-/Delete-Änderungen, unlesbare oder zu lange Diffs ⇒ blockiert; die angezeigte Diff wird aus den Blobs erzeugt, nicht von Git | `…_policy.py`, `…_workspace.py` |
| Export (V3) | exakter Commit aus der Objektdatenbank in ein neues Temp-Verzeichnis: ohne `.git`, ohne Filter/autocrlf, nur versionierte Dateien, Manifest + SHA-256, Symlinks/Submodule/Sonderzeichen/Case-Kollisionen abgelehnt, nachträgliche Differenz (extra/fehlende/geänderte Datei, `.git`-Ordner) erkannt | `…_workspace.py` |
| Freigabe (V5) | Titel/Problem erscheinen nur als **zitierte, escapte Einzelzeile**, gekennzeichnet „[unverifizierter Text]“; alles „[JARVIS]“ stammt aus Code; der vollständige Diff (ESC-maskiert) ist Teil des Dialogs, nicht darstellbare Diffs sind nicht freigabefähig; Freigabe an Commit, Diff-Digest, Test-Manifest und exakten Anzeige-Digest gebunden; **Aktivierung fragt erneut**; nur ein einzelnes „Ja“ zählt | `…_workflow.py`, `…_policy.py` |
| Parallelität/Audit | Sperre je Vorschlag (zweite Operation wird abgelehnt), Status wird vor jedem Schreiben neu gelesen und per CAS geschrieben; Freigabe/Aktivierung/Rollback brauchen funktionierendes Audit (kein Logger, kein Sink, Fehler, Exception ⇒ abgelehnt) | `…_workflow.py` |
| Prozess-Härtung | nur feste Argumentlisten, Object-IDs werden gegen `[0-9a-f]{40}` geprüft (auch aus dem Speicher), Ausgabe hart begrenzt, Timeout/Abbruch. Prozessbaum: **Linux** Prozessgruppe + vorab gefundene Nachfahren (`/proc`); **Windows** ein *Kill-on-close-Job-Object* je Prozess (`winjob.py`), nur als Rückfall `taskkill /T` über absoluten Pfad – `taskkill /T` allein erreicht verwaiste Enkel **nicht** und ist keine Garantie. Fehlerfälle des Job-Objects sind plattformneutral mit einer Fake-API getestet; die echte Win32-Schicht wird nur von den `win_`-Tests geprüft | `…_workspace.py`, `…_process_tree.py` |

Die Logik von Freigabe, Export, Pipeline und Aktivierung ist implementiert, aber **nicht erreichbar** (kein Vorschlag kann `TESTED` erreichen). Sie wird nur mit einem **Test-Double** der Isolations-Bescheinigung und einem In-Memory-Workspace getestet; das beweist die Logik, nicht eine Sandbox.

### Nur Heuristik – kein Sicherheitsbeweis
- **AST-Prüfung** (`policy.static_findings`): Import-Allow-List, verbotene Namen/Attribute/Dunder, ersetzt die frühere Regex-Denylist und schließt deren dokumentierte Umgehungen (Kommentar im String, Unicode-Look-alikes, mehrzeilig, `from os import …`, `getattr`, `__builtins__`, Datei-/Umgebungs-/Netzwerk-Module). Sie ist ein **Filter**: Verhalten, das vorhandener, erlaubter Code zur Laufzeit tut, sehen statische Regeln nicht (z. B. Abschwächen einer Prüfung durch Ändern von Werten oder Bedingungen). Ein bestandener Scan **autorisiert keine Ausführung**.
- **Allow-List** schützt vor Änderungen an den gelisteten Sicherheitsbereichen; sie sagt nichts darüber, ob eine Änderung an einer erlaubten Datei fachlich richtig ist.
- Tests mit Marker `detection_only` prüfen solche Filter und beweisen keine Isolation.

### Warum keine Ausführung (V1) – nicht nachgewiesene Isolation
Ein `git worktree` ist **keine Sandbox**. Ein Prozess, der vorgeschlagenen Code importiert oder testet, hat die Rechte des JARVIS-Benutzers: Er kann das Home-Verzeichnis und Zugangsdaten lesen, beliebige Dateien schreiben (auch `.git/hooks` des Haupt-Repositories, auf das die `.git`-Datei des Worktrees verweist), Netzwerkverbindungen öffnen und abgekoppelte Kindprozesse starten, die einen Timeout überleben. Eine bereinigte Umgebung entfernt nur Variablen. Im Sicherheitsexperiment wurde so ein Edit mit `open(<fremde Datei>)` vorbereitet, „getestet“ und hat außerhalb des Worktrees gelesen und geschrieben. Deshalb: `ExecutionGuard` bleibt gesperrt (`isolation.py`), `allow_prepare`/`allow_activation`/`repo_path` werden abgelehnt, und Tests auf vorgeschlagenem Code dürfen **nicht** ausgeführt werden, bis eine Sandbox **alle** folgenden Eigenschaften auf Linux **und** Windows durch eigene Tests nachweist: eigener unprivilegierter Benutzer bzw. gleichwertige Isolation · kein Zugriff auf Host-Credentials und fremde Dateien (nur eine schreibgeschützte Kopie des Exports) · kein Netzwerk · keine Verbindung zum Haupt-Repository (der Export hat kein `.git`) · begrenzte CPU/Speicher/Laufzeit/Ausgabe/Prozesse · zuverlässiges Beenden **aller** Kindprozesse · plattformspezifische Tests. Ein solches Backend existiert nicht.

### Bekannte Grenzen und offene Punkte
- **Keine Sandbox** (siehe oben): offene Lücke bis zum Nachweis; die Ausführungsstufen sind bewusst nicht aktivierbar.
- **Speicher:** Der HMAC schützt nur gegen Schreiber **ohne** Schlüssel. Wer Datei **und** Schlüssel kontrolliert, kann beliebig schreiben; das Wiedereinspielen einer **älteren gültig signierten** Datei nach einem Neustart wird nicht erkannt (innerhalb eines Prozesses schon). Der Schlüssel liegt als Datei (0600) bzw. in einer Umgebungsvariable; ein OS-Schlüsselbund wird nicht verwendet. Die Fernhaltung des Coding-Agents beruht auf der Startprüfung der Pfade, nicht auf einer PathGuard-Regel. **Schlüsseldatei:** POSIX: Modusbits werden bei jedem Laden geprüft (getestet). Windows: `chmod` wirkt dort nicht; stattdessen wird die *effektive* ACL (SDDL, geerbte Einträge eingeschlossen) gelesen und nur aktueller Benutzer, SYSTEM und Administratoren zugelassen, andere Konten ⇒ fail closed; eine neu angelegte Datei wird zuerst leer erzeugt, per `icacls` eingeschränkt und verifiziert und erst dann beschrieben (atomar veröffentlicht); eine bestehende Datei wird **nie** automatisch geändert. Die Entscheidungslogik ist mit SDDL-Beispielen auf allen Plattformen getestet; **der echte PowerShell/icacls-Weg ist nur durch die `win`-Tests in `test_self_improvement_keyfile.py` prüfbar und war beim Schreiben unter Windows nicht ausgeführt**. Nicht reproduzierbar ohne zweites Konto: ein tatsächlicher Zugriffsversuch eines anderen Benutzers. **`data_dir`** wird relativ zum Arbeitsverzeichnis aufgelöst (nicht zur Konfigurationsdatei); der Default wurde bewusst nicht geändert, weil es keine Migration gibt. Der tatsächliche absolute Ort steht im Status (`data_dir`), unter OneDrive erscheint eine Warnung (Sync kann die Datei sperren und lädt sie hoch).
- **Analyse** liest den In-Memory-Verlauf der Engines und den Audit-Log-Tail; es gibt keine Laufzeit-Metriken über Neustarts hinweg (und es werden keine erfunden). „Betroffene Dateien“ der Vorschläge sind Komponentenhinweise.
- **Audit nach der Tat:** Der Absichts-Eintrag wird vor Freigabe/Aktivierung/Rollback geschrieben (fail closed); schlägt ein späterer Ergebnis-Eintrag fehl, wird das nur geloggt.
- **LLM-Ausgaben** (Formulierungen) sind Daten: in Dialogen und CLI immer zitiert/escaped; das Entwerfen von Edits gehört zum (gesperrten) Vorbereiten.
- **Windows:** Seit diesem Stand gibt es Windows-spezifischen Code (Schlüssel-ACL, Job Object) und Windows-Tests dafür (`…_keyfile.py`, `…_process_tree.py`, `test_security_paths_windows.py` für Junctions/Reparse Points der PathGuard). Sie sind unter Linux **übersprungen** (mit Grund) und beweisen dort nichts; die Aussagen gelten erst nach einem Lauf unter Windows. Weiterhin ungeprüft: `msvcrt`-Sperre in Randfällen, Verhalten von OneDrive-Platzhaltern, Geräte-Namen (`CON`, `NUL`) in Pfaden, lange Pfade, Prozesse, die schon vor der Job-Zuweisung Kinder starten (das Anhängen erfolgt nach dem Start). Die Job-Objekte sind **Containment, keine Sandbox**.
- Aktivierung/Rollback wären nach einem Merge erst nach Neustart wirksam; der Code dafür ist gesperrt.

### Tests
`tests/test_self_improvement_{analysis,policy,store,workflow,workspace,security}.py` (+ `tests/si_util.py`). Es wird **kein** vorgeschlagener Code ausgeführt: adversariale Beispiele sind Strings (AST/Speicher/Rendering), der Workflow läuft gegen einen In-Memory-Workspace und einen Fake-Runner, der Kommandos nur aufzeichnet; echte Unterprozesse sind ausschließlich `git` (Metadaten-/Objekttests auf Temp-Repos) und testeigene Hilfsskripte für den Prozess-Runner. Ein Meta-Test verbietet `eval/exec/compile/__import__` in diesen Testdateien.

## Business / Research / Finance v1 (Phase 10)

JARVIS kann komplexe **Informations- und Analyseaufgaben** bearbeiten: recherchieren, Quellen vergleichen, Wettbewerber und Märkte analysieren, Geschäftsmodelle durchrechnen, Kennzahlen und Risiken berechnen, Trading-Ideen als **Paper-Trades** durchspielen. Es gibt **keine neue Architektur**: die drei Fähigkeiten sind gewöhnliche Agenten des Phase-7-Systems, geplant von der Goal Engine, ausgeführt vom `AgentOrchestrator`, mit Abhängigkeiten über `AgentTask.dependencies`.

```
Goal Engine ─▶ GoalPlanner/AgentPlanner ─▶ AgentOrchestrator ─▶ Research Agent ──▶ (ToolGateway ─▶ browser-Tool ─▶ PermissionEngine ─▶ BrowserController)
                                                  │                  │ research_result (Parent-Result)
                                                  ├────────────▶ Business Agent  (keine Tools)
                                                  └────────────▶ Finance Agent   (keine Tools)
```
**Nur Research hat ein Tool (`browser`).** Business und Finance haben **gar keines**: sie rechnen auf Eingaben und Research-Ergebnissen, können nichts lesen, schreiben, senden oder bestellen.

### Research Agent (`src/jarvis/research/`)
Ablauf: `Anfrage → ResearchPlan → Quellenauswahl (URL-Policy) → Abruf (browser-Tool) → Extraktion → Cross-Check → Synthese → ResearchResult`.
- **Plan:** `objective`, `questions`, `urls`, `max_sources` (≤ 20), `max_actions` (≤ 200), `timeout` (≤ 1800 s), optional `allowed_domains`/`excluded_domains`, `follow_links` (relevante Links derselben Seite). Eingaben können Limits nur **senken**.
- **Quellen:** jede mit `url`, `title`, `source` (Host), `retrieved_at`, `relevance` und `status` (`ok` / `unavailable` / `blocked` / `skipped`). Was nicht lesbar war, steht als `unavailable` im Ergebnis – es wird nichts ergänzt. Seiten gelten nie als „aktuell“, außer mit dem gespeicherten Abrufzeitpunkt.
- **Aussagen:** `FACT` (eine Quelle sagt es, mit URL), `INFERENCE` (von JARVIS aus belegten Zahlen berechnet, z. B. Preisspanne), `OPINION` (Werbe-/Meinungsaussage), `UNCERTAIN` (abgeschwächt oder in einem Widerspruch). Dieselbe Aussage in ≥ 2 Quellen (inkl. gleicher Zahlen) ist `corroborated`.
- **Widersprüche:** Zahlen derselben Größe, die verschiedene Quellen über 10 % auseinander angeben, werden als `CONFLICT` mit **allen** Seiten dargestellt.
- **URL-Filter (vor dem Browser, nie großzügiger als der Browser):** nur `http(s)`; abgelehnt werden `javascript:`, `data:`, `file:`, `ftp:` …, Zugangsdaten in der URL, **Backslashes** (mehrdeutig), interne/private/Loopback-/Link-Local-Adressen und -Namen (auch `2130706433`, `0x7f.1`, `[::ffff:127.0.0.1]`), Cloud-Metadaten-Hosts. Interne Hosts nur, wenn **du** sie in `browser.private_hosts_allowed` freigegeben hast. Geheime Query-Parameter (`token`, `key`, `password` …) und Tracking-Parameter werden entfernt; Duplikate (auch `www.`) werden nur einmal gelesen. DNS wird nicht aufgelöst (wie beim Browser, siehe Grenzen).
- **Sicherheit bleibt beim Browser:** jede Navigation prüft weiter der `BrowserController` und fragt die `PermissionEngine` (Rückfrage je Seite). Verweigerung ⇒ Task `BLOCKED`, kein Retry. Research klickt, füllt und lädt nichts: erlaubte Browser-Aktionen im Code sind genau `status, start, goto, text, links, stop`. Weiterleitung auf eine abgelehnte Adresse ⇒ Inhalt wird verworfen. Secrets im Seitentext werden geschwärzt.

### Business Agent (`src/jarvis/business/`)
Aufgabenarten (`input.kind`): `market_analysis`, `competitor_analysis`, `business_plan`, `business_analysis` (eigene Zahlen: Schwachstellen), `marketing_draft`, `lead_list`.
- **`BusinessResult`:** `objective`, `summary`, `findings`, `market_data`, `competitors`, `opportunities`, `risks`, `assumptions`, `recommendations`, `sources`, `confidence` (Stufe, Score, Gründe) – jede Zahl/Aussage trägt ihre **Basis**: `GIVEN` (vom Nutzer), `FACT` (Quelle), `INFERENCE` (berechnet), `ESTIMATE` (Annahme, sagt woraus), `UNKNOWN` (keine Daten). Fehlende Daten bleiben `UNKNOWN`; ein Preis aus widersprüchlichen Quellen wird **nicht** übernommen.
- **Rechnungen:** Break-even, Szenarien, Amortisation, Preisstatistik, Periodenanalyse – nur aus gegebenen Zahlen; Kontributionsmarge ≤ 0 ⇒ `UNKNOWN` mit Begründung.
- **Marketing/Leads:** Entwürfe aus **gegebenen** Fakten (Zielgruppe, Angebot, USPs), als `DRAFT` markiert; Lead-Listen nennen nur öffentliche Seiten aus der Recherche. **Gesendet wird nichts**: Aufgaben wie `send_email`, `outreach`, `send_offer`, `contract`, `payment`, `publish` enden `BLOCKED (external_action_not_supported)`. Jede Kontaktaufnahme wäre eine eigene YELLOW-Aktion über die PermissionEngine mit deiner ausdrücklichen Bestätigung.
- Konkrete Branchen (Fahrzeugaufbereitung, -vermietung, Online-Projekte …) sind **nicht** einkodiert – es sind normale Ziele mit eigenen Daten.

### Finance Agent (`src/jarvis/finance/`)
Aufgabenarten: `financial_analysis` (KGV/P/E, P/S, EV/EBITDA, Wachstum, Margen, Verschuldung, Free Cash Flow), `company_analysis` (Vergleich mehrerer Unternehmen), `risk_analysis` (Drawdown, Volatilität, Rendite), `scenario_analysis`, `portfolio_analysis`, `paper_trade_analysis`.
- **Kennzahlen sind `COMPUTED` oder `UNKNOWN`** (fehlende Daten, Nenner ≤ 0, zu wenige Datenpunkte) – nie geschätzt. Zahlen kommen aus deiner Eingabe oder als **belegte** Figuren aus Research-Ergebnissen (`from_research`, mit Quelle). Keine Marktdaten-API: Daten, die nicht gegeben sind, fehlen.
- **Modelle:** `TradeIdea` (symbol, direction, entry, stop, target, position_size, risk_amount, risk_reward, confidence, thesis, invalidations, timestamp), `PaperTrade`, `RiskAssessment`, `Position`, `PortfolioSnapshot`, `RiskLimits`. Symbole und Zahlen werden streng validiert (keine Leerzeichen, URLs, Befehle; endlich, positiv).
- **Paper-Trading:** eine Idee wird auf einem **gegebenen** Kursverlauf durchgespielt (`target` / `stop` / `open` / `not_entered`; Stop vor Ziel im selben Balken). Risikolimits (`max_risk_per_trade_pct`, `max_position_pct`, `max_total_exposure_pct`, `daily_loss_limit_pct`, **Hebel 1.0**, **keine Abhebungen**) werden geprüft; ist die Kontogröße unbekannt, gilt die Prüfung als **nicht bestanden**.
- **Keine Echtgeld-Funktion:** Anfragen wie `place_order`, `buy`, `sell`, `transfer`, `withdraw`, `broker_login` enden `BLOCKED (live_trading_not_supported)`; `finance.paper_trading_only = false` und `max_leverage != 1` werden **beim Start abgelehnt**. Es gibt keinen Broker-Code, kein Order-Objekt, keine gespeicherten Freigaben. Eine spätere Echtgeld-Schicht müsste jede Aktion als YELLOW + ausdrückliche Bestätigung über die PermissionEngine führen.

### Goal Engine
Templates werden **ausdrücklich** gewählt (`context={"template": …}`), nie aus dem Chat erraten: `research_web`, `market_analysis`, `competitor_analysis`, `business_analysis`, `business_plan`, `financial_analysis`, `company_analysis`, `paper_trade_analysis`; Daten in `research`/`business`/`finance`-Blöcken des Kontexts (ohne Daten wird nichts erfunden: Ziel endet `BLOCKED`). Ketten: Research → Business (→ Finance), z. B. `business_plan` mit `finance={"kind": "scenario_analysis", …}`. Das Ergebnis des Vorgängers reicht der Orchestrator als Parent-Result durch (die Goal Engine setzt nur `AgentTask.dependencies`). Ein unbekannter `kind` (z. B. `place_order`) scheitert schon an der Plan-Validierung – es entsteht kein Task.

### CLI und `/run`
`/research`, `/business`, `/finance` (je auch `status`) zeigen: aktiv/deaktiviert, registrierter Agent, aktive Tasks, Limits, Fähigkeiten. Kleine, nebenwirkungsfreie **GREEN-Rechenwerkzeuge** laufen über ToolRegistry → PermissionEngine:
```
/run research action=check_url url=https://example.com/preise?utm_source=x
/run business action=break_even fixed_costs=1200 price=50 variable_cost=15
/run business action=price_stats values=50,80,52.5
/run finance action=risk_reward direction=long entry=100 stop=95 target=115
/run finance action=position_size account=10000 risk_pct=1 entry=100 stop=95
/run finance action=pe price=100 eps=5
/run finance action=drawdown prices=100,120,90,130
```
Es gibt dort keine Aktion zum Bestellen, Überweisen, Senden oder Einloggen. Analysen laufen über Goals/Core: `core.create_goal(…, context={"template": …})` / `/goal` (siehe Goal Engine).

### Datenschutz und Memory
Nichts wird dauerhaft gespeichert: weder Recherche-, Finanz-, Trading- noch Business-Ergebnisse. Memory nur auf deine ausdrückliche Anweisung über die bestehende Memory-Architektur („merk dir diese Wettbewerbsanalyse“). Ergebnisse sind begrenzt (`max_result_chars`) und geschwärzt; Zugangsdaten werden nirgends verwendet.

### Konfiguration (Umgebung: `JARVIS_RESEARCH_*`, `JARVIS_BUSINESS_*`, `JARVIS_FINANCE_*`)
`[research]` `enabled=false`, `max_sources=8` (≤ 20), `max_actions=40` (≤ 200), `timeout_seconds=300` (≤ 1800), `max_result_chars`; `[business]` `enabled=false`, `max_steps=20` (≤ 100), `timeout_seconds=120` (≤ 600); `[finance]` `enabled=false`, `max_steps=50` (≤ 1000), **`paper_trading_only=true`** (false wird abgelehnt), `timeout_seconds=120`, Risikolimits (`max_risk_per_trade_pct=1`, `max_position_pct=20`, `max_total_exposure_pct=100`, `daily_loss_limit_pct=3`, `max_leverage=1`). Alle drei brauchen `agents.enabled`; Research zusätzlich `browser.enabled`. Parallelität begrenzt der Orchestrator (`agents.max_concurrent`).

### Tests
`tests/test_research_units.py`, `test_research_agent.py` (gegen die echte PermissionEngine mit Fake-Browser), `test_business_units.py`, `test_finance_units.py`, `test_analysis_goals.py` (Goal Engine → Research → Business → Finance, Fehler-Isolation, Timeout, Abbruch, Verweigerung), `test_analysis_security.py` (AST-/Quellscans, Beweise: kein Browser-Bypass, kein Nachrichtenversand ohne Berechtigung, keine Echtgeld-Aktion, kein ToolGateway-Bypass), `test_analysis_integration.py` (Config, Bootstrap, CLI, `/run`, Memory), `test_analysis_real.py` (echter Browser via Playwright gegen drei lokale Wettbewerber-Seiten, echte Threads/Timer; optional `JARVIS_TEST_PUBLIC_WEB=1` liest `https://example.com/`). Unter Windows: `.\.venv\Scripts\python.exe -m pytest tests/test_research_units.py tests/test_research_agent.py tests/test_business_units.py tests/test_finance_units.py tests/test_analysis_goals.py tests/test_analysis_security.py tests/test_analysis_integration.py tests/test_analysis_real.py -vv -rs`.

### Bekannte Grenzen (v1)
- **Keine Websuche:** Research liest die ihm gegebenen URLs (und optional relevante Links derselben Seite). Das Browser-Tool maskiert Query-Werte in Links; eine Suchmaschinen-Anbindung wäre unzuverlässig und ist nicht enthalten.
- Der Browser liefert keinen HTTP-Status: eine „404“-Seite mit Text wird als Seite gelesen; Inhalte sind nicht verifiziert, nur zitiert.
- Extraktion und Klassifikation sind regelbasiert (Deutsch/Englisch, Preise in €/$/%); es gibt keine semantische Zusammenfassung und kein LLM. Marktgröße, Bewertungen u. Ä. erscheinen nur, wenn eine Quelle sie nennt – sonst `UNKNOWN`.
- Der URL-Filter löst keine DNS-Namen auf (ein öffentlicher Name, der auf eine private Adresse zeigt, wird weder hier noch im Browser erkannt).
- Finance kennt keine Live-Kurse/Finanzberichts-APIs; Daten müssen gegeben oder recherchiert sein. Ergebnisse sind Analyse, keine Anlageberatung.
- Marketing-/Lead-Funktionen bereiten vor; es wird nichts versendet oder veröffentlicht.
- Nicht enthalten (ausdrücklich): Echtgeld-Trading, Broker-Login, Überweisungen/Abhebungen, automatische Verträge/Kaltakquise, Self-Modification, Credential-Verwaltung, persistente Finanzdaten.

## Notaus (Phase 14, Teilziel 1)

`/notaus` (CLI) bzw. der rote Knopf **NOTAUS** (GUI) setzt einen zentralen Latch in der Berechtigungs-Engine: ab sofort wird **jede** Anfrage verweigert (auch GREEN), `core.handle`
`core.plan`/`chat`, Gedächtnisänderungen, neue Ziele/Reparaturen, CLI-`/voice` und `/improve` (außer `list`/`show`) lehnen ab, und alle Komponenten werden nebenläufig unter einer Frist gestoppt (Halt der Controller, Abbruch von Zielen/Agenten-Tasks/Reparaturläufen,
GUI: Eingabe gesperrt, offene Bestätigungen abgelehnt, Sprachmodus beendet). Der Bericht nennt jede Komponente ehrlich als *stopped / requested / nothing / failed / timeout*;
ein Fehler macht den Notaus *unvollständig*. **Nicht rückgängig** gemacht und nicht als beendet gemeldet werden bereits ausgeführte externe Aktionen; eine laufende
`core.handle`-Anfrage lässt sich nicht unterbrechen. Aufheben nur mit `/notaus reset` bzw. „Notaus aufheben …“ und ausdrücklicher Bestätigung (nur *Einmal erlauben*; mit
`security.confirmation = "deny"` ist ein Aufheben im laufenden Prozess nicht möglich). Der Notaus ist kein Tool und nicht persistent. Details und Grenzen: `docs/PHASE14_AUTONOMY.md`.

## Sitzungsbudget (Phase 14, Teilziel 4)

Optional (`[budget] enabled = true`, Standard **aus**): eine gemeinsame Obergrenze für Tool-Aufrufe (`max_tool_calls`, hart 100000) und Laufzeit (`max_runtime_seconds`, hart 86400)
über alle Ziele und Agenten des Prozesses. Die Berechtigungs-Engine prüft sie direkt nach dem Notaus und bucht erst bei der Genehmigung (jeder genehmigte Aufruf zählt, auch GREEN;
verweigerte und `evaluate()` verbrauchen nichts); die Laufzeit beginnt mit der ersten genehmigten Aktion. Bei Überschreitung werden weitere Aktionen verweigert (Regel `invariant:budget`,
Meldung mit Verbrauch, ein Audit-Ereignis `budget_exhausted`); nichts Laufendes wird abgebrochen, der Notaus hat Vorrang. Kein Zurücksetzen, keine Erhöhung im laufenden Prozess, kein
Tool kann es verändern; `/budget` zeigt den Verbrauch nur lesend. Ein Neustart beginnt eine neue Sitzung. Details: `docs/PHASE14_AUTONOMY.md`.

## Grafische Oberfläche (Phase 11)

Ein Tkinter-Fenster um denselben Core wie die CLI (kein zweiter Core, keine zweite Berechtigungslogik): Gespräch per Text oder Sprache, sichtbare Zustände, ein
schreibgeschützter Statusbereich und die Bestätigungsdialoge der Berechtigungs-Engine.

```
pip install -e ".[voice]"            # nur für den Sprachmodus (sounddevice + numpy); die Texteingabe braucht es nicht
jarvis-gui                           # oder: python -m jarvis.interface.gui [-c jarvis.local.toml]
```
`tkinter` ist nötig (unter Windows im Python-Installer und bei `actions/setup-python` enthalten; unter Linux `python3-tk`). Die Konfiguration wird wie bei der CLI
gelesen (`jarvis.local.toml`, sonst `config/jarvis.toml`).

**Bedienung.** Reiter *Gespräch*: Eingabe + Enter oder „Senden“. Der Verlauf gilt nur für die laufende Sitzung (nicht gespeichert; Erinnerungen laufen weiter über
Memory). Zeilen mit `/` sind dieselben Befehle wie in der CLI (`/help`, `/tasks`, `/run …`; sie laufen durch dieselbe Berechtigungsprüfung); `/voice` startet den
GUI-Sprachmodus, `/exit` schließt das Fenster. Reiter *Status*: „Aktualisieren“ liest **nur lesend** Subsystemstatus, `/tasks`, `/goals` und `/permissions` und zeigt unter „Laufende Arbeit“ alle nicht beendeten Ziele, Agenten-Tasks, Reparaturläufe und gespeicherten Pläne mit je einem Knopf *Abbrechen*; der Knopf ruft nur das passende `cancel` auf (kooperativ: eine Meldung wie „Abbruch angefordert“ heißt nur, dass er angefordert ist; nicht unterstützte oder bereits beendete Abbrüche werden als „Nicht abgebrochen“ mit der Antwort der Schnittstelle gezeigt; Abbrechen geht auch bei aktivem Notaus, startet aber nie etwas). Ziele, Agenten und Self-Repair sind standardmäßig aus; dann steht dort „Keine laufende Arbeit“ und welche Quellen ausgeschaltet sind; ein
Abschnitt, der sich nicht lesen lässt, sagt das, statt zu fehlen. Es gibt keine neue autonome Ausführung und keine zusätzlichen Rechte.

**Zustände** (oben rechts; angezeigt nur, wenn die Komponente ihn meldet – nichts ist animiert oder erfunden):

| Zustand | Wann |
|---|---|
| Bereit | nichts läuft |
| Zuhören | der Sprachmodus wartet auf / nimmt eine Äußerung auf (Mikrofon aktiv) |
| Verarbeiten | eine Anfrage läuft (Text oder Sprache) |
| Sprechen | die Sprachausgabe läuft |
| Wartet auf Bestätigung | ein Bestätigungsdialog ist offen (höchste Priorität) |
| Fehler | ein unerwarteter Fehler bei einer Anfrage oder ein Sprachfehler; der Grund steht unter dem Eingabefeld, bis zur nächsten Aktion |

Die Farben/Zustände stehen in `STATE_STYLE` (`gui.py`) und `UiState` (`gui_model.py`); weitere Zustände oder Animationen kommen dort hinzu.

**Sprachmodus.** Nur auf ausdrücklichen Klick auf „Sprache starten“ (oder `/voice`), nie automatisch; das Mikrofon ist nur solange aktiv. Benutzt wird die vorhandene
`VoiceSession` (Mikrofon → STT → Core → TTS); Wake-Word, Sprache und Provider kommen aus `[voice]`. Voraussetzungen: `voice.stt_provider` **nicht** `console`
(z. B. `openai` mit `OPENAI_API_KEY`/`JARVIS_VOICE_API_KEY`), ein Mikrofon samt PortAudio (`sounddevice`), ein Ausgabeweg (`tts_provider`). Fehlt etwas, steht der Grund im
Gespräch und die Texteingabe bleibt voll nutzbar. Während des Sprachmodus ist das Tippen gesperrt (ein Gespräch gleichzeitig). „Sprache beenden“ (oder das Wort „exit“)
beendet ihn nach der laufenden Aufnahme (höchstens `voice.max_record_seconds`).

**Bestätigungen.** Der Dialog (einmal / Sitzung / ablehnen, Timeout 120 s) lehnt bei jedem Fehler, Timeout, beim Schließen und bei einer geschlossenen GUI ab. Eine
ausdrückliche `security.confirmation = "deny"` wird nicht überschrieben.

**Schließen.** Läuft noch eine Anfrage oder der Sprachmodus, fragt das Fenster nach. Beim Schließen starten keine neuen Aktionen, offene Bestätigungen werden abgelehnt,
Subsysteme mit Notaus (`halt`) werden angehalten, das Ergebnis einer noch laufenden Anfrage wird verworfen. Eine bereits laufende `core.handle`-Anfrage selbst lässt sich
nicht unterbrechen; ihr (Daemon-)Thread endet mit dem Prozess.

**Threads.** Hintergrundthreads (Anfrage, Sprache, Status, Bestätigung) fassen keine Widgets an: sie legen Ereignisse in eine Queue, die der GUI-Thread alle 50 ms abholt.

**Tests.** `tests/test_gui_model.py` (alle Plattformen, ohne Tk), `tests/test_gui_view.py` und `tests/test_gui_confirmation.py` (echtes Tk-Fenster; ohne tkinter/Anzeige
übersprungen), `tests/test_voice_state.py`. Windows: CI-Job `gui-windows` (siehe `docs/TESTING.md`). **Nur manuell prüfbar:** Aussehen/Skalierung des Fensters, echtes Mikrofon,
echte Lautsprecher, Bedienung mit der Maus.

**Grenzen.** Kein Streaming der Antworten, Unterbrechen der Sprachausgabe nur über `interrupt()` (barge-in), keine Animationen, kein persistenter Verlauf, keine Barrierefreiheitsprüfung,
Mehrmonitor-/DPI-Verhalten nicht gesondert behandelt.

## Tests & Entwicklungsworkflow

```bash
pytest            # 1249 Tests: config, llm, tasks, tools, planner, core, e2e, CLI, voice, memory, security, computer
                  # (ohne Mikrofon/Netzwerk/echte Maus; 11 Tests laufen real auf einem virtuellen X11-Display (Xvfb) und werden sonst übersprungen)
```
Workflow: Schnittstelle in `base.py` definieren → Implementierung → Test mit `MockProvider` (kein Netzwerk nötig) → `pytest`.
Verdrahtung ausschließlich in `jarvis/bootstrap.py` (Composition Root).

## Architektur

```
src/jarvis/
├── config.py, errors.py, logging_setup.py   Basis
├── bootstrap.py                             Composition Root (einzige Stelle, die konkrete Klassen verdrahtet)
├── llm/        base (Interface) · mock · http_providers (OpenAI, Anthropic) · factory (Registry)
├── core/       JarvisCore (Orchestrierung) · Context (Gesprächsverlauf)
├── planning/   Planner (Ziel → Task)
├── tasks/      Task, TaskStatus, TaskManager
├── tools/      Tool, ToolRegistry, builtin/
├── permissions/ levels · request · decision · engine · policy · paths · resources · grants · confirmation · audit · factory
├── redaction.py Neutrale Secret-Erkennung (von Memory und Permissions geteilt)
├── computer/   backend (Provider-Interfaces) · controller · tools · safety · resources · validation · screenshots · vision · policy · factory · providers/{fake,mss_screen,pyautogui_input,win32_windows,xlib_windows,subprocess_apps}
├── agents/     Multi-Agent: Orchestrator · Planner · Registry · Adapter
├── goals/      Goal Engine: models · state · planner · validation · evaluator · engine · context · policy · factory · fake
├── research/ · business/ · finance/   Phase 10: Recherche (Browser-Tool), Business-Analysen, Finanz-Analyse/Paper-Trading (Agenten, keine eigene Infrastruktur)
├── self_repair/ Self-Testing/-Repair: models · state · policy · context · tester · diagnostics · planner · evaluator · engine · factory · fake
├── memory/     base (Interface) · models · validation · ranking · sqlite_store · inmemory · null · guard · guarded · extraction · factory
├── voice/      base (Interfaces) · session · factory · console · mock · devices · openai_provider · system_tts
└── interface/  cli
```
```
User ─▶ CLI ─▶ JarvisCore ─┬─▶ Context ─▶ LLMProvider ─▶ Antwort (CHAT)
                           └─▶ Planner ─▶ Task(+Subtasks) ─▶ TaskManager (PLAN)
                                  └─ kennt ToolRegistry
```
Memory ist ein eigenständiges Paket ohne Abhängigkeit zu Core, Voice oder Agenten (per Test erzwungen); der Core bekommt nur ein `MemoryStore`-Objekt injiziert.

Voice ist eine weitere Oberfläche *um* den Core (`Mikrofon → STT → handle(text) → Response → TTS`); der Core bleibt textbasiert und kennt Audio nicht.

Abhängigkeiten zeigen nach innen: Core kennt nur Interfaces (`LLMProvider`, `Tool`), nie konkrete Anbieter.

### Architekturentscheidungen

1. **Python, src-Layout, stdlib-only zur Laufzeit.** Schneller Start, beste KI-Ökosystem-Basis, keine Versionskonflikte. Anbieter-HTTP via `urllib` statt SDKs; SDKs lassen sich später als weitere Provider registrieren.
2. **Provider-Registry statt if/else.** `register_provider(name, factory)` – neue Backends (lokale Modelle) ohne Core-Änderung.
3. **Mock-Provider als Default.** Das System startet und testet offline und deterministisch; echte Modelle sind reine Konfiguration.
4. **Dependency Injection per Konstruktor.** `JarvisCore` bekommt Provider, Tools, Tasks, Context, Planner injiziert.
5. **Planner mit Fallback.** Unbrauchbare LLM-Antworten führen zu einem generischen Plan statt zu Abbruch (Designgrundsatz „nicht bei Komplexität aufgeben“). `task.result["plan_source"]` kennzeichnet die Herkunft.
6. **Task-Statusautomat mit erlaubten Übergängen.** Verhindert inkonsistente Zustände, wenn später Agenten parallel Tasks ändern. Geplante Tasks stehen auf `WAITING` (Plan bereit, Ausführung ausstehend).
7. **Tools sind fehlerisoliert und permission-geprüft.** `execute` wirft nie; RED ist immer verboten, YELLOW nur mit `confirmed=True`. Das ist die Grundlage für Phase 13.
8. **Routing per Heuristik** (`looks_like_goal`) – bewusst simpel, ersetzbar durch eine Decision Engine.
9. **Secrets nur aus der Umgebung**, `api_key` ist aus `repr` ausgeschlossen.
10. **Voice als Front-End, nicht als Core-Teil.** `VoiceSession` ruft nur `handle(text)`; STT/TTS/Mikrofon/Player sind vier getrennte, per Registry austauschbare Schnittstellen. Sprachlogik (Wake-Word, Exit, Sprech-Zusammenfassung) liegt in der Session, nicht im Core.
11. **Konsolen-Voice als Default.** Die gesamte Sprachschleife ist ohne Hardware lauffähig und testbar; echte Engines sind reine Konfiguration.
12. **Optionale Hardware-Abhängigkeit, lazy importiert.** `sounddevice` ist ein Extra; fehlt es, entsteht `VoiceUnavailableError` statt eines Importfehlers. Weiterhin keine Pflicht-Abhängigkeiten.
13. **Wake-Word auf Transkript-Basis.** Heißt: bei `require_wake_word` läuft das Mikrofon/STT dauerhaft (Kosten/Privatsphäre bei Cloud-STT). Ein lokaler Hotword-Detektor lässt sich über `voice.hotword_detector` davorschalten (`HotwordGatedSource`).
14. **Konfiguration generisch:** Umgebungsvariablen `JARVIS_<SECTION>_<FIELD>` werden aus den Dataclasses abgeleitet; neue Abschnitte brauchen keine Verdrahtung.
15. **Memory hinter `MemoryStore`, Richtlinien als Decorator.** Secret-Filter und Limits liegen in `GuardedMemoryStore`, nicht in den Backends; so gelten sie für jedes künftige Backend. Basisvalidierung (Typen, Längen) liegt gemeinsam in `validation.py`.
16. **SQLite, stdlib, lazy.** Datei/Schema entstehen erst beim ersten Schreiben (`PRAGMA user_version` als Migrationsanker); Tags in eigener Tabelle für exakte Filter; keine ORM-/Treiberabhängigkeit.
17. **Zwei Backends von Anfang an** (`sqlite`, `memory`) mit identischen Vertragstests – beweist, dass die Schnittstelle nicht an SQLite hängt.
18. **Nur ausdrückliches Merken.** Zuverlässige automatische Extraktion braucht ein LLM/Bewertung (spätere Phase); bis dahin ist alles Dauerhafte eine bewusste Handlung.
19. **Privacy-by-default:** Memory-Inhalte gehen nur mit `use_in_prompts = true` an ein LLM. Die Suche ist keyword-basiert – bewusst, damit auch ohne externe Dienste alles lokal bleibt.
21. **Tools beschreiben, die Registry fragt.** Ein Tool kennt die Engine nicht und kann Entscheidungen nicht formen; nur `ToolRegistry.execute` ruft `tool.run` auf (per AST-Test geprüft).
22. **`ProtectedTool` statt Vertrauen.** `run` ist versiegelt und prüft bei jedem Aufruf einen engine-ausgestellten, an Tool + Argumente gebundenen, einmaligen Grant. Nicht-GREEN-Tools müssen in strikten Registries `ProtectedTool` sein.
23. **Engine nur anheben, nie absenken; Schalter schreibgeschützt.** Level, Aktionsboden, RED-Invariante, Lockdown; Konfiguration der Engine ist nach dem Bau read-only.
24. **Fail closed überall**, inkl. nicht beschreibbarem Audit-Log, Provider-Fehlern und kaputten Regeln; Policy-Fehler verhindern den Start.
25. **Neutrales `jarvis.redaction`.** Memory und Permissions teilen die Secret-Erkennung, ohne voneinander abzuhängen.
26. **Phase 13 vor Phase 4 vorgezogen**, weil Computersteuerung ohne belastbares Rechtesystem riskant ist (Empfehlung aus Phase 1, jetzt umgesetzt).
27. **Computer Control als Tools + Controller + Provider.** Fünf kleine Provider-Schnittstellen (Screen, Maus, Tastatur, Fenster, Apps) bilden einen austauschbaren `ComputerBackend`; Bibliotheken werden nur lazy in Providern importiert (Import-Hazards wie `KeyError`/`SystemExit` abgefangen).
28. **Der Controller erzwingt die Berechtigung selbst.** `execute(plan)` braucht einen zu Tool/Aktion/Ressource passenden Grant; Pläne sind signiert; Planung liest nur, handeln tut erst `execute`. Ausführung rekonstruiert den Plan aus dem *aktuellen* Zustand (Zielbindung).
29. **Ressourcen sind URIs** (`screen://`, `keyboard://`, `window://`, `app://`) vom Typ `other`: Policy-Globs funktionieren ohne Änderung der Engine; Tipptext ist nie Teil einer Ressource.
30. **RED wird vom Tool beantragt, von der Engine entschieden** – und im Audit festgehalten, nicht als stiller Fehler verschluckt. Eingebaute Sperrlisten sind nur erweiterbar.
31. **Beobachten GREEN, Handeln YELLOW, Tastatur/Schließen immer gefragt** (Baseline-Regeln in der Engine statt Sonderlogik).
32. **Opt-in und degradierend:** `enabled = false` ist Standard; fehlende Bibliothek/Display → Subsystem „unavailable“ mit Grund, JARVIS startet normal; Installation der Sicherheitsregeln ist atomar (bei Fehler Rollback, keine Tools).
33. **Engine minimal verschärft, nicht ersetzt:** zusätzliche Aktions-Verben im Level-Boden, RED-Grund in der Ablehnung.
34. **Reale Verifikation auf X11/Xvfb** mit denselben Providern und Tools wie unter Windows (außer dem Win32-Fensterprovider), weil nur dort echte Eingaben geprüft werden konnten.
35. **Ordnerstruktur schlank gehalten:** Platzhalter-Pakete für künftige Module (agents, memory, …) werden erst mit ihrer Phase angelegt, nicht leer vorab.

## Vorbereitung für spätere Phasen

| Phase | Anschlusspunkt |
|---|---|
| 2 Voice ✅ | `voice/` – siehe oben. Barge-in-Schnittstelle und austauschbarer Hotword-Baustein vorhanden (kein mitgelieferter Detektor). Offen: Streaming-STT/TTS |
| 3 Memory ✅ | `jarvis/memory/`. Lokale, netzfreie Suche (gehashte TF-IDF-Vektoren, `memory.backend`) vorhanden; Verlauf abgeschlossener Arbeit optional in SQLite (`[history]`, nur Anzeige). Offen: echte Embeddings, Fortsetzen von Tasks nach Neustart (`TaskManager` hinter Interface), automatische Extraktion, Zusammenfassung/Verfall alter Einträge |
| 4 Computer ✅ | `jarvis/computer/`; Provider austauschbar (`register_backend`), Beobachten→Handeln→Prüfen vorbereitet |
| 5–6 Browser/Coding | neue `ProtectedTool`-Klassen mit `describe_action` (Host/Pfad/Command als Ressource); Policy-Regeln pro Tool; Vision über `ImageObserver` |
| 7 Multi-Agent ✅ · 8 Goal Engine ✅ | `jarvis/agents/`, `jarvis/goals/`; Goal Engine nutzt nur die `AgentOrchestrator`-Schnittstelle |
| 9 Self-Repair ✅ | `jarvis/self_repair/`; nutzt nur Coding-Agent-Tasks über den Orchestrator; Proposer-Schnittstelle für spätere intelligentere Reparaturvorschläge |
| 13 Security ✅ | `jarvis/permissions/` + `ToolRegistry.execute` als einzige Kontrollstelle. GUI-Bestätigung ✅ (`GUIConfirmationProvider`). Offen: OS-Sandbox/Subprozess-Isolation, Hash-verkettetes Audit-Log, Voice-Bestätigung, Netzwerk-/Geld-Policies |
| 10 Business/Research/Finance ✅ | `jarvis/research|business|finance/`; Echtgeld-Schicht (Broker) fehlt bewusst: müsste YELLOW + ausdrückliche Bestätigung nutzen |
| 15 Self-Improvement | Provider-/Tool-Registry erlauben Austausch und Rollback von Komponenten |

## Zukünftige Phasen

1 Core ✅ · 2 Voice ✅ · 3 Memory ✅ · 4 Computer Control ✅ · 5 Browser/Internet ✅ · 6 Coding Agent ✅ · 7 Multi-Agent ✅ · 8 Goal Engine ✅ ·
9 Self-Testing/Repair ✅ · 10 Business/Research/Finance ✅ (volle Suite auf Windows- und Linux-Runner grün) · 11 GUI ✅ (siehe Abschnitt „Grafische Oberfläche“; Fenster-, Voice- und Notaus-Tests laufen in der Windows-CI, Mikrofon/Lautsprecher bleiben manuell) · 12 Smartphone (nicht begonnen) · 13 Permissions/Security ✅ (vorgezogen) · 14 Maximum Autonomy (nur Teilziele 1–4, ohne neue Autonomie; Hintergrundziele/Selbststart bewusst nicht implementiert) · 15 Self-Improvement (deaktivierter Vorschlagsworkflow, keine Sandbox).
Phase 13 wurde vor Phase 4 vorgezogen (Begründung: Computersteuerung ohne belastbares Rechtesystem ist riskant).
