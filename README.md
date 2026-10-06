# JARVIS

Modulares, persönliches KI-Assistenzsystem. Langfristiges Ziel: ein autonomer Agent, dem man ein Ziel nennt und der selbstständig
**denkt → plant → recherchiert → programmiert → handelt → testet → repariert → lernt → neue Fähigkeiten entwickelt**.

**Status: Phase 1 (Core MVP) und Phase 2 (Voice Interface) abgeschlossen.** JARVIS führt Pläne noch nicht autonom aus – Architektur und Schnittstellen dafür stehen.

## Was bisher funktioniert (Phase 1 + 2)

- Konfiguration (Defaults < TOML < Umgebungsvariablen), Dev-/Produktionsmodus, Logging, Fehlerhierarchie
- LLM-Abstraktion: `mock` (offline), `openai`, `anthropic` – austauschbar per Konfiguration
- Core: Input → Kontext → Routing → LLM oder Planner → strukturierte `Response`
- Task-System mit Status-Automat, Subtasks, Ergebnis/Fehler, benötigten Tools/Agenten
- Tool-System: Registry, dynamische Registrierung, fehlerisolierte Ausführung, Permission-Level
- Planner: Ziel → Task mit Subtasks (LLM-JSON, mit Template-Fallback, damit nie „zu komplex“ zurückkommt)
- CLI (`jarvis>`)
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

## Tests & Entwicklungsworkflow

```bash
pytest            # 105 Tests: config, llm, tasks, tools, planner, core, e2e, CLI, voice (ohne Mikrofon/Netzwerk)
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
├── voice/      base (Interfaces) · session · factory · console · mock · devices · openai_provider · system_tts
└── interface/  cli
```
```
User ─▶ CLI ─▶ JarvisCore ─┬─▶ Context ─▶ LLMProvider ─▶ Antwort (CHAT)
                           └─▶ Planner ─▶ Task(+Subtasks) ─▶ TaskManager (PLAN)
                                  └─ kennt ToolRegistry
```
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
15. **Ordnerstruktur schlank gehalten:** Platzhalter-Pakete für künftige Module (agents, memory, …) werden erst mit ihrer Phase angelegt, nicht leer vorab.

## Vorbereitung für spätere Phasen

| Phase | Anschlusspunkt |
|---|---|
| 2 Voice ✅ | `voice/` – siehe oben. Offen: Streaming-STT/TTS, Unterbrechen (barge-in), lokaler Hotword-Detektor |
| 3 Memory | `Context` und `TaskManager` hinter Interfaces mit persistenter Implementierung austauschen; Voice nutzt nur `handle(text)` und profitiert automatisch |
| 4–6 Computer/Browser/Coding | neue `Tool`-Klassen, Permission-Level pro Tool |
| 7–8 Multi-Agent, Goal Engine | `Task.required_agents`/`subtasks` sind belegt; Executor-Schleife über Subtasks fehlt noch |
| 9 Self-Repair | Task-Übergang `FAILED → PENDING` (Retry) existiert |
| 13 Security | `permissions` + `ToolRegistry.execute` als zentrale Kontrollstelle |
| 15 Self-Improvement | Provider-/Tool-Registry erlauben Austausch und Rollback von Komponenten |

## Zukünftige Phasen

1 Core ✅ · 2 Voice ✅ · 3 Memory · 4 Computer Control · 5 Browser/Internet · 6 Coding Agent · 7 Multi-Agent · 8 Goal Engine ·
9 Self-Testing/Repair · 10 Business/Research/Finance · 11 GUI · 12 Smartphone · 13 Permissions/Security · 14 Maximum Autonomy · 15 Self-Improvement.
Empfehlung für eine spätere Änderung: Permissions/Security (13) vor Computer Control (4) vorziehen, da Computersteuerung ohne belastbares Rechtesystem riskant ist.
