# JARVIS

Modulares, persönliches KI-Assistenzsystem. Langfristiges Ziel: ein autonomer Agent, dem man ein Ziel nennt und der selbstständig
**denkt → plant → recherchiert → programmiert → handelt → testet → repariert → lernt → neue Fähigkeiten entwickelt**.

**Status: Phase 1 (Core MVP), Phase 2 (Voice Interface) und Phase 3 (Memory) abgeschlossen.** JARVIS führt Pläne noch nicht autonom aus – Architektur und Schnittstellen dafür stehen.

## Was bisher funktioniert (Phase 1–3)

- Konfiguration (Defaults < TOML < Umgebungsvariablen), Dev-/Produktionsmodus, Logging, Fehlerhierarchie
- LLM-Abstraktion: `mock` (offline), `openai`, `anthropic` – austauschbar per Konfiguration
- Core: Input → Kontext → Routing → LLM oder Planner → strukturierte `Response`
- Task-System mit Status-Automat, Subtasks, Ergebnis/Fehler, benötigten Tools/Agenten
- Tool-System: Registry, dynamische Registrierung, fehlerisolierte Ausführung, Permission-Level
- Planner: Ziel → Task mit Subtasks (LLM-JSON, mit Template-Fallback, damit nie „zu komplex“ zurückkommt)
- CLI (`jarvis>`)
- **Memory (Phase 3):** persistentes lokales Langzeitgedächtnis (SQLite) hinter der Schnittstelle `MemoryStore`, mit Secret-Schutz; gemerkt wird nur auf ausdrücklichen Wunsch
- **Voice (Phase 2):** Speech-to-Text → `JarvisCore.handle` → Text-to-Speech als zusätzliche Oberfläche, mit Wake-Word, Exit-Phrasen und Fallback bei fehlender Hardware

## Installation

Python ≥ 3.11. Keine Laufzeit-Abhängigkeiten.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Konfiguration

Vorrang (niedrig → hoch): eingebaute Defaults → `config/jarvis.toml` (oder `jarvis.local.toml`, `-c PFAD`, `JARVIS_CONFIG`) → Umgebungsvariablen.

| Variable | Bedeutung |
|---|---|
| `JARVIS_MODE` | `development` (Log DEBUG) / `production` (Log INFO) |
| `JARVIS_LOG_LEVEL`, `JARVIS_LOG_DIR` | Logging |
| `JARVIS_LLM_PROVIDER` | `mock` (Default), `openai`, `anthropic` |
| `JARVIS_LLM_MODEL`, `_TEMPERATURE`, `_MAX_TOKENS`, `_TIMEOUT`, `_BASE_URL` | Modell-Parameter |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `JARVIS_LLM_API_KEY` | API-Keys (nur per Umgebung, nie in Dateien) |

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
CLI-Befehle: `/plan <ziel>`, `/tasks`, `/tools`, `/reset`, `/help`, `/exit`. Eingaben, die mit einem Aufgabenverb beginnen
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
Das Wake-Word wird auf dem *Transkript* erkannt (kein Offline-Hotword-Detektor; Phase-2-Kompromiss, siehe unten).
Exit-Phrasen: `exit`, `quit`, `stop`, `stopp`, `beenden`, `beende`, `tschüss`, `goodbye`.

Konfiguration im Abschnitt `[voice]` von `config/jarvis.toml` oder per `JARVIS_VOICE_<FELD>`
(`STT_PROVIDER`, `TTS_PROVIDER`, `AUDIO_INPUT`, `AUDIO_OUTPUT`, `LANGUAGE`, `WAKE_WORD`, `REQUIRE_WAKE_WORD`, `SPEAK_RESPONSES`,
`SAMPLE_RATE`, `MAX_RECORD_SECONDS`, `SILENCE_SECONDS`, `SILENCE_THRESHOLD`, `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`, `TTS_COMMAND`,
`BASE_URL`, `TIMEOUT`). API-Keys nur über die Umgebung.

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
| `backend` / `JARVIS_MEMORY_BACKEND` | `sqlite` | `sqlite` oder `memory` (nicht persistent); eigene via `register_backend` |
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

## Tests & Entwicklungsworkflow

```bash
pytest            # 339 Tests: config, llm, tasks, tools, planner, core, e2e, CLI, voice, memory (ohne Mikrofon/Netzwerk, temporäre DBs)
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
├── permissions/ GREEN / YELLOW / RED
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
13. **Wake-Word auf Transkript-Basis.** Heißt: bei `require_wake_word` läuft das Mikrofon/STT dauerhaft (Kosten/Privatsphäre bei Cloud-STT). Ein lokaler Hotword-Detektor kann später als weiterer `AudioSource` ergänzt werden.
14. **Konfiguration generisch:** Umgebungsvariablen `JARVIS_<SECTION>_<FIELD>` werden aus den Dataclasses abgeleitet; neue Abschnitte brauchen keine Verdrahtung.
15. **Memory hinter `MemoryStore`, Richtlinien als Decorator.** Secret-Filter und Limits liegen in `GuardedMemoryStore`, nicht in den Backends; so gelten sie für jedes künftige Backend. Basisvalidierung (Typen, Längen) liegt gemeinsam in `validation.py`.
16. **SQLite, stdlib, lazy.** Datei/Schema entstehen erst beim ersten Schreiben (`PRAGMA user_version` als Migrationsanker); Tags in eigener Tabelle für exakte Filter; keine ORM-/Treiberabhängigkeit.
17. **Zwei Backends von Anfang an** (`sqlite`, `memory`) mit identischen Vertragstests – beweist, dass die Schnittstelle nicht an SQLite hängt.
18. **Nur ausdrückliches Merken.** Zuverlässige automatische Extraktion braucht ein LLM/Bewertung (spätere Phase); bis dahin ist alles Dauerhafte eine bewusste Handlung.
19. **Privacy-by-default:** Memory-Inhalte gehen nur mit `use_in_prompts = true` an ein LLM. Die Suche ist keyword-basiert – bewusst, damit auch ohne externe Dienste alles lokal bleibt.
20. **Ordnerstruktur schlank gehalten:** Platzhalter-Pakete für künftige Module (agents, memory, …) werden erst mit ihrer Phase angelegt, nicht leer vorab.

## Vorbereitung für spätere Phasen

| Phase | Anschlusspunkt |
|---|---|
| 2 Voice ✅ | `voice/` – siehe oben. Offen: Streaming-STT/TTS, Unterbrechen (barge-in), lokaler Hotword-Detektor |
| 3 Memory ✅ | `jarvis/memory/`. Offen: semantische/Vektor-Suche (neues Backend, `MemoryHit.score` ist vorbereitet), persistente Tasks (`TaskManager` hinter Interface, Ergebnisse als `task_result`), automatische Extraktion, Zusammenfassung/Verfall alter Einträge |
| 4–6 Computer/Browser/Coding | neue `Tool`-Klassen, Permission-Level pro Tool |
| 7–8 Multi-Agent, Goal Engine | `Task.required_agents`/`subtasks` sind belegt; Executor-Schleife über Subtasks fehlt noch |
| 9 Self-Repair | Task-Übergang `FAILED → PENDING` (Retry) existiert |
| 13 Security | `permissions` + `ToolRegistry.execute` als zentrale Kontrollstelle |
| 15 Self-Improvement | Provider-/Tool-Registry erlauben Austausch und Rollback von Komponenten |

## Zukünftige Phasen

1 Core ✅ · 2 Voice ✅ · 3 Memory ✅ · 4 Computer Control · 5 Browser/Internet · 6 Coding Agent · 7 Multi-Agent · 8 Goal Engine ·
9 Self-Testing/Repair · 10 Business/Research/Finance · 11 GUI · 12 Smartphone · 13 Permissions/Security · 14 Maximum Autonomy · 15 Self-Improvement.
Empfehlung für eine spätere Änderung: Permissions/Security (13) vor Computer Control (4) vorziehen, da Computersteuerung ohne belastbares Rechtesystem riskant ist.
