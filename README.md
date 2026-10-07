# JARVIS

Modulares, persönliches KI-Assistenzsystem. Langfristiges Ziel: ein autonomer Agent, dem man ein Ziel nennt und der selbstständig
**denkt → plant → recherchiert → programmiert → handelt → testet → repariert → lernt → neue Fähigkeiten entwickelt**.

**Status: Phase 1 (Core MVP), Phase 2 (Voice), Phase 3 (Memory), Phase 13 (Permissions & Security, vorgezogen) und Phase 4 (Computer Control) abgeschlossen.** JARVIS führt Pläne noch nicht autonom aus – Architektur und Schnittstellen dafür stehen.

## Was bisher funktioniert (Phase 1–4, 13)

- Konfiguration (Defaults < TOML < Umgebungsvariablen), Dev-/Produktionsmodus, Logging, Fehlerhierarchie
- LLM-Abstraktion: `mock` (offline), `openai`, `anthropic` – austauschbar per Konfiguration
- Core: Input → Kontext → Routing → LLM oder Planner → strukturierte `Response`
- Task-System mit Status-Automat, Subtasks, Ergebnis/Fehler, benötigten Tools/Agenten
- Tool-System: Registry, dynamische Registrierung, fehlerisolierte Ausführung, Permission-Level
- Planner: Ziel → Task mit Subtasks (LLM-JSON, mit Template-Fallback, damit nie „zu komplex“ zurückkommt)
- CLI (`jarvis>`)
- **Computer Control (Phase 4):** Bildschirm, Maus, Tastatur, Fenster und Anwendungen als `ProtectedTool`s – jede Aktion läuft durch die Berechtigungs-Engine; opt-in, Windows-first (`pyautogui` + `mss` + Win32 über `ctypes`), austauschbare Provider
- **Permissions & Security (Phase 13):** Jede Tool-Ausführung läuft durch eine Berechtigungs-Engine (GREEN/YELLOW/RED, Regeln, Bestätigung, Pfad-Sicherheit, Audit-Log, Secret-Schutz) und schlägt im Zweifel fehl (fail closed)
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
| 2 Voice ✅ | `voice/` – siehe oben. Offen: Streaming-STT/TTS, Unterbrechen (barge-in), lokaler Hotword-Detektor |
| 3 Memory ✅ | `jarvis/memory/`. Offen: semantische/Vektor-Suche (neues Backend, `MemoryHit.score` ist vorbereitet), persistente Tasks (`TaskManager` hinter Interface, Ergebnisse als `task_result`), automatische Extraktion, Zusammenfassung/Verfall alter Einträge |
| 4 Computer ✅ | `jarvis/computer/`; Provider austauschbar (`register_backend`), Beobachten→Handeln→Prüfen vorbereitet |
| 5–6 Browser/Coding | neue `ProtectedTool`-Klassen mit `describe_action` (Host/Pfad/Command als Ressource); Policy-Regeln pro Tool; Vision über `ImageObserver` |
| 7–8 Multi-Agent, Goal Engine | `Task.required_agents`/`subtasks` sind belegt; Executor-Schleife über Subtasks fehlt noch |
| 9 Self-Repair | Task-Übergang `FAILED → PENDING` (Retry) existiert |
| 13 Security ✅ | `jarvis/permissions/` + `ToolRegistry.execute` als einzige Kontrollstelle. Offen: OS-Sandbox/Subprozess-Isolation, Hash-verkettetes Audit-Log, Voice/GUI-Bestätigung, Netzwerk-/Geld-Policies |
| 15 Self-Improvement | Provider-/Tool-Registry erlauben Austausch und Rollback von Komponenten |

## Zukünftige Phasen

1 Core ✅ · 2 Voice ✅ · 3 Memory ✅ · 4 Computer Control ✅ · 5 Browser/Internet · 6 Coding Agent · 7 Multi-Agent · 8 Goal Engine ·
9 Self-Testing/Repair · 10 Business/Research/Finance · 11 GUI · 12 Smartphone · 13 Permissions/Security ✅ (vorgezogen) · 14 Maximum Autonomy · 15 Self-Improvement.
Phase 13 wurde vor Phase 4 vorgezogen (Begründung: Computersteuerung ohne belastbares Rechtesystem ist riskant).
