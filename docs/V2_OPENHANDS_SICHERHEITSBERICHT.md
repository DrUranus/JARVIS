# OpenHands: statische Telemetrie- und Sicherheitsprüfung des öffentlichen Quellcodes

**Status: Prüfbericht. Es wurde nichts installiert oder ausgeführt, kein Code in JARVIS übernommen.** Der Quellcode wurde mit Besitzerfreigabe nur zur Analyse heruntergeladen (flacher `git clone --depth 1` in ein Scratchpad außerhalb des Projekts, Hooks abgeschaltet) und nur gelesen und durchsucht. Release-Freeze, V1-Abnahme #186, PermissionEngine, X0, Not-Aus und Audit bleiben unberührt. Ergänzt `docs/V2_SANDBOX_VORSCHLAG.md`.

**Geprüfter Stand:** `OpenHands/OpenHands` Commit `7b5aa9eb60bd` (2026-11-10, Canvas/Frontend, TypeScript) und `OpenHands/software-agent-sdk` Commit `06b358764bb7` (2026-11-11, Python: `openhands-sdk`, `-agent-server`, `-tools`, `-workspace`). Pfade unten relativ zu diesen Repositories; `AS` = `software-agent-sdk/openhands-agent-server/openhands/agent_server`.

**Kennzeichnung:** **Nachgewiesen** = im gelesenen Code mit Fundstelle. **Folgerung** = logische Ableitung aus Nachgewiesenem. **Vermutung/ungeprüft** = nicht im Code belegt. **Grenzen der Methode:** nur statische Lektüre ausgewählter Module; keine Laufzeitbeobachtung, kein Test des tatsächlichen Verhaltens, keine Prüfung der Abhängigkeiten (`litellm`, `posthog`, `docker`-Images, npm-Pakete) im Quelltext, keine vollständige Durchsicht aller 1590 Python-Dateien. Treffer können durch andere Codepfade ergänzt oder überstimmt werden.

## 1. Kurzfassung
1. **Server-Telemetrie des Agent-Servers ist standardmäßig aus und doppelt abgesichert** (Exporter `none`, Zustimmung `unset` = nicht erteilt, Abschaltschalter `DO_NOT_TRACK`). Nachgewiesen.
2. **Die Canvas-Oberfläche sendet dagegen ohne Zustimmung ein anonymes Installationsereignis** an `z.openhands.dev` (PostHog-Proxy), außer es ist abgeschaltet. Nachgewiesen. Für JARVIS nur relevant, wenn die Oberfläche genutzt würde; ein reiner Agent-Server-/SDK-Betrieb enthält diesen Pfad nicht.
3. **Das SDK-Docker-Sandbox-Modul (`DockerWorkspace`) ist nicht gehärtet:** keine Capability-Beschränkung, kein Benutzerwechsel, keine Ressourcenlimits, keine Netzsperre, Host-Umgebungsvariablen werden mit Wert auf der Kommandozeile weitergereicht, Mounts beliebig und standardmäßig schreibend. Nachgewiesen. Die **je-Konversation-Container** des Agent-Servers sind teilweise gehärtet (kein root, `--cap-drop ALL`, `no-new-privileges`, Limits), haben aber **keine Netzwerkbeschränkung** und einen `host.docker.internal`-Eintrag. Nachgewiesen.
4. **Kein Standardbetrieb enthält eine Netzsperre.** Also muss JARVIS sie selbst erzwingen (siehe Abschnitt 8).
5. **Dynamische Downloads** gibt es, aber nach Code standardmäßig aus oder nutzergesteuert (öffentliche Skills, Erweiterungsarchive mit Hash, ACP-Provider via `npx`, Image-Pull). Nachgewiesen, mit Einschränkungen unten.
6. **Standardbetrieb ohne Sitzungsschlüssel läuft ohne Authentifizierung.** Nachgewiesen (`AS/dependencies.py:38`).

## 2. Telemetrie
### 2.1 Agent-Server (Python)
| Befund | Status | Fundstelle |
|---|---|---|
| Zustimmung wird aus Einstellungen/Umgebung aufgelöst; `DO_NOT_TRACK` (1/true/yes/on) erzwingt „aus“ vor allem anderen | nachgewiesen | `AS/telemetry/policy.py:98` (`kill_switch_engaged`), `:160` (`resolve`) |
| Ohne gespeicherte oder per Umgebung gesetzte Zustimmung: `enabled=False`, Grund `default` | nachgewiesen | `AS/telemetry/policy.py:214` |
| Exporter-Standard ist `none`, d. h. nie Auslieferung | nachgewiesen | `AS/config.py:172-173` |
| PostHog/HTTP-Exporter wird nur gebaut, wenn `exporter` ausdrücklich `posthog`/`http` ist **und** Schlüssel/Endpunkt gesetzt sind; sonst `None` | nachgewiesen | `AS/telemetry/service.py:56-86` |
| PostHog-Standardhost (nur bei aktivem Exporter) `https://us.i.posthog.com`; Geolokalisierung und Ausnahme-Autoerfassung aus | nachgewiesen | `AS/config.py:188-189`, `AS/telemetry/posthog_exporter.py:35,56,58,86` |
| Ereignisse werden bereinigt/pseudonymisiert (Konversations-ID mit Salt, kein Rohtraceback) | nachgewiesen (Konzept im Code), Wirksamkeit nicht geprüft | `AS/telemetry/factory.py` (`conversation_ref`), `AS/telemetry/sanitizer.py` |
| Zusätzliche Überwachung (OpenTelemetry/Laminar) startet nur, wenn eine der Variablen `LMNR_PROJECT_API_KEY`, `OTEL_ENDPOINT`, `OTEL_EXPORTER_OTLP_*` gesetzt ist | nachgewiesen | `software-agent-sdk/openhands-sdk/openhands/sdk/observability/laminar.py:28,345` |
| Die je-Konversation-Container erhalten diese Beobachtungsvariablen nur, wenn sie auf dem Host gesetzt sind | nachgewiesen | `AS/docker_runtime/registry.py` (Schleife `_OBSERVABILITY_ENV_VARS`, vor Zeile 671) |

**Folgerung:** Wenn JARVIS den Server nie mit `exporter=posthog|http` konfiguriert, `DO_NOT_TRACK=1` und keine OTEL-/LMNR-Variablen setzt, ist keine Serverseitige Telemetrie aktiv. **Ungeprüft:** ob unveränderte Pakete (z. B. `litellm`, `posthog`, `opentelemetry`) eigene Verbindungen aufbauen; das erfordert Laufzeitbeobachtung (Wegwerf-Prototyp, Netz mitschneiden, OH-12).

### 2.2 Canvas-Oberfläche (TypeScript, nur wenn die UI genutzt würde)
| Befund | Status | Fundstelle |
|---|---|---|
| `trackInstall()` wird beim ersten Rendern aufgerufen und sendet `canvas_install` an PostHog **ohne** Zustimmung; Daten laut Kommentar: Browserplattform, User-Agent, Referrer, Origin-URL, „embedded“-Status, zufällige ID | nachgewiesen | `OpenHands/src/hooks/use-telemetry.ts:70-81`, `src/services/telemetry.ts:9,751,763,775` |
| Standardziel `https://z.openhands.dev` (Reverse-Proxy zum PostHog-US-Projekt); Schlüssel aus Build oder Standardkonfiguration | nachgewiesen | `src/services/telemetry.ts:76-77` |
| Abschalten: `VITE_DO_NOT_TRACK=1`, Browser-DNT, oder `AGENT_CANVAS_DISABLE_TELEMETRY=1` / `--disable-telemetry` am statischen Server | nachgewiesen (laut Kommentar und Skript) | `src/services/telemetry.ts:21-29`, `scripts/static-server.mjs` |
| Autocapture und Sitzungsaufzeichnung aus; Seitenaufrufe nur nach Zustimmung (Opt-out standardmäßig) | nachgewiesen | `src/services/telemetry.ts:430-442` |
| Die Datenschutzerklärung nennt Drittanbieter-Analyse und „Do Not Track“ wird nicht beachtet | aus früherer Doku-Prüfung | `openhands.dev/privacy` (2025-09-03) |

**Folgerung:** Für JARVIS keine Nutzung der Canvas-UI; falls doch, vorher `AGENT_CANVAS_DISABLE_TELEMETRY=1` und Netz zu `z.openhands.dev` sperren. Ob die Electron-Variante einen Auto-Updater hat, wurde mit `grep` auf `autoUpdater|electron-updater|checkForUpdates` in `electron/`, `package.json`, `electron-builder.config.mjs` **nicht** gefunden (kein Treffer; kein Beweis für Abwesenheit).

## 3. Netzwerkverbindungen und eingebaute Zielhosts (SDK-Quellcode, Python-Dateien)
Auswertung aller `https?://`-Literale der vier Pakete. Relevante dauerhafte Ziele (Auswahl, mit Bedeutung):
| Host | Bedeutung | Status |
|---|---|---|
| `llm-proxy.app.all-hands.dev` | OpenHands-eigener LLM-Proxy (Modellpräfix `openhands/`), `AS`-unabhängig in `openhands-sdk/.../llm/utils/openhands_provider.py:11,40` | nur bei Modellen mit diesem Präfix bzw. Proxy-Basis-URL; nicht nach Code Standard |
| `llm-proxy.app.all-hands.dev/vllm` | Standard-Endpunkt des **Critic** (`critic/impl/api/client.py:74`) | Critic Standard **aus** (`settings/model.py:385-386`). **Bei Aktivierung wird der LLM-Schlüssel des Nutzers (`critic_api_key or llm.api_key`, `settings/model.py:1776`) an diesen Host gesendet.** Nachgewiesen |
| `app.all-hands.dev`, `runtime.all-hands.dev` | Cloud-/Remote-Workspaces (`openhands-workspace/.../cloud/workspace.py`, `remote_api/workspace.py`) | nur wenn diese Workspaces benutzt werden |
| `github.com/OpenHands/extensions` | öffentliche Skills (Abschnitt 4) | Standard **aus** |
| `us.i.posthog.com`, `api.lmnr.ai` | PostHog-/Laminar-Exporter | nur bei Konfiguration (Abschnitt 2) |
| `api.openai.com`, `chatgpt.com`, `auth.openai.com`, `platform.claude.com`, `openrouter.ai` u. a. | Anbieter/OAuth-Flüsse der Modellanbindung | nur bei gewähltem Anbieter |
| `unpkg.com`, `huggingface.co`, `www.reddit.com`, `www.google.com` | Beispiele, Browser-/Tool-Ziele, Dokumentationsstrings | im Code als Zeichenkette; Aufruf nicht im Einzelnen geprüft |

**Modellkommunikation:** Der Aufruf läuft über die Bibliothek **LiteLLM** (`openhands-sdk/.../llm/llm.py:83-119`, `api_base`/`base_url` konfigurierbar, `drop_params` Standard wahr, `:522`). Ziel ist, was der Nutzer als `base_url` setzt; **ob Daten außer dem eigentlichen Modellaufruf abfließen, hängt von LiteLLM und dem Anbieter ab (nicht geprüft).** Es gibt in diesem Quellcode keinen Hinweis, dass `LITELLM_LOCAL_MODEL_COST_MAP` gesetzt wird (Suche ohne Treffer); ob LiteLLM beim Import eine Preisliste aus dem Netz holt, ist **Vermutung/ungeprüft** und gehört in den Laufzeittest (OH-12).
**Bilder:** http(s)-Bild-URLs werden nur für Modelle heruntergeladen, die es verlangen (`requires_inline_image_data`, `llm.py:3033-3036`), mit SSRF-Sperre (`image_inline.py:1-17`). Nachgewiesen.

## 4. Dynamische Downloads und Codeausführung
| Pfad | Verhalten | Standard | Fundstelle |
|---|---|---|---|
| Öffentliche Skills | `git clone` bzw. Aktualisierung von `https://github.com/OpenHands/extensions` nach `~/.openhands/skills-cache/`; Ref `main` (per `EXTENSIONS_REF` änderbar); lokal ohne Netz über `EXTENSIONS_PATH` | **aus** (`load_public_skills: bool = False`) | `openhands-sdk/.../skills/skill.py:1170-1176,1262-1300`; `context/agent_context.py:101-102` |
| Erweiterungsarchive (Canvas-Erweiterungen) | Download eines `tar.gz` mit erwartetem SHA-256, Abbruch bei Abweichung; Altlast-Clients laden/starten nichts implizit | nutzergesteuert | `AS/canvas_extensions/backend.py:330-391`, `AS/canvas_extensions_router.py:324` |
| ACP-Provider | Start über `npx` mit Fallback, Cache-Vorwärmung kann Pakete herunterladen | nur mit ACP-Agent | `openhands-sdk/.../agent/acp_agent.py:493,2796-2797` |
| Git | `git fetch origin` für Worktree-Start, `git clone` bei Repo-Einrichtung | nur bei entsprechenden Funktionen | `AS/conversation_service.py:154`, `openhands-sdk/.../workspace/repo.py:465-470` |
| Image | Standard `ghcr.io/openhands/agent-server:latest-python`; Image-Build zieht Pakete aus dem Netz | beim Pull/Build | Doku; `AS/docker/Dockerfile` (u. a. `uv`, `npm`, Chromium) |
| Browser-Werkzeug | Chromium im Image; Zugriff auf beliebige Webseiten | `OH_ENABLE_BROWSER` | `AS/docker/Dockerfile`, `registry.py:671ff.` |
| MCP-Server | vom Nutzer konfigurierte Prozesse/Endpunkte | keine voreingestellt (nicht vollständig geprüft) | `openhands-sdk/.../mcp` (nicht gelesen) |

**Folgerung:** Das Verbot unkontrollierter Downloads (R11) lässt sich nur durch **vorab geprüftes Image mit Digest, `load_public_skills=False`, keinen Browser, kein ACP, kein MCP und Netz zu** einhalten.

## 5. Container, Mounts, Netz, Privilegien
### 5.1 `DockerWorkspace` (SDK, `software-agent-sdk/openhands-workspace/openhands/workspace/docker/workspace.py`)
Nachgewiesen:
- `docker run -d --rm --ulimit nofile=65536:65536 --name … <flags> <image> --host 0.0.0.0 --port 8000` (`:243-262`). **Keine** Flags für Benutzer, Capabilities, `no-new-privileges`, Speicher, CPU, Prozesse, Netzwerk (`:208-262`).
- Beliebige Mounts über `volumes` mit `-v` (`:220-221`), ohne erzwungenes `:ro`.
- Host-Umgebungsvariablen aus `forward_env` werden **als `-e KEY=Wert` auf der Kommandozeile** übergeben (`:216-218`); Standardliste `DEBUG`, `SESSION_API_KEY`, `OH_SESSION_API_KEYS_0` (`:89-96`). Ein Wert auf der Kommandozeile ist für andere lokale Prozesse sichtbar (`docker inspect`, Prozessliste) – **Folgerung**.
- Port nur auf Loopback veröffentlicht (`-p 127.0.0.1:…:8000`, `:224`); Container-intern hört der Server auf `0.0.0.0`.
- Optional `--network <name>` (`:237-238`); ohne Angabe gilt das Docker-Standardnetz mit Internetzugang (**Folgerung** aus fehlendem Flag).

### 5.2 Je-Konversation-Container des Agent-Servers (`AS/docker_runtime/registry.py`)
Nachgewiesen:
- `docker run -d --rm --user <UID>:<GID> --cap-drop ALL --security-opt no-new-privileges --ulimit core=0 --add-host host.docker.internal:host-gateway --label … -p 127.0.0.1::8000 …` (`:722-741`), Limits `--memory`, `--cpus`, `--pids-limit` aus der Konfiguration (`:707-717`).
- Mounts: Konversationsordner, Persistenz, Arbeitsordner, Worktrees (+ Repo-/Git-Verzeichnisse bei Worktrees) als `-v host:target` **ohne `:ro`** (`:696-704`) – der Arbeitsordner ist also schreibbar.
- Weitergereichte Umgebung: nur Namen (`-e NAME`), u. a. `HOME`, `OH_SECRET_KEY`, Sitzungsschlüssel (`:671-685`).
- **Kein** `--network none` und keine Egress-Begrenzung; `host.docker.internal` zeigt auf den Host (**Folgerung:** der Container kann Dienste auf dem Windows-Host erreichen, soweit diese auf einer erreichbaren Schnittstelle lauschen).
- Benutzer im Image: Nicht-root-Benutzer (`AS/docker/Dockerfile:444,683`); Start per `tini` (`:705`).

### 5.3 Authentifizierung
Ohne konfigurierte Sitzungsschlüssel wird **keine** Prüfung durchgeführt (`AS/dependencies.py:38`: Prüfung nur `if config.session_api_keys and …`); `_default_session_api_keys` liefert eine leere Liste, wenn keine Variable gesetzt ist (`AS/config.py:43-53`). **Folgerung:** Server immer mit gesetztem Schlüssel starten, nur an Loopback.

## 6. Geheimnisse
- `SecretRegistry` hält Geheimnisse und maskiert sie in Ausgaben; sie werden bei Bedarf als Umgebungsvariablen in Befehle eingeblendet (`openhands-sdk/.../conversation/secret_registry.py:163,219-283`). Nachgewiesen. **Ob maskierte Werte vorher in Modellanfragen gelangen, ist nicht geprüft.**
- `OH_SECRET_KEY` verschlüsselt gespeicherte Konversationswerte und fällt auf den ersten Sitzungsschlüssel zurück (`AS/config.py` Beschreibung um Zeile 208). Nachgewiesen.
- Export von Verläufen schwärzt Geheimnisse (`AS/_secret_redaction.py`, `AS/file_router.py:208`). Nachgewiesen (Konzept).
- **Risiko:** der LLM-Schlüssel steht in der Konfiguration des Agenten (`llm.api_key`) und ist damit im Container-Prozess. Mit einem **Host-Relay** (siehe `V2_SANDBOX_VORSCHLAG.md`, R10) steht stattdessen nur ein wertloser Platzhalter im Container.

## 7. Bewertung gegen unsere Anforderungen (R1–R13)
| Anforderung | Ergebnis |
|---|---|
| R1 Dateisystem | Standard-Mounts schreibbar → **nur mit eigener Startvorlage** erfüllbar (Kopie, `:ro`, tmpfs). |
| R2 Netz | Kein Standard-Netzschutz → **nur durch eigene Netzsperre** (`--network none` bzw. internes Netz + Relay). |
| R3 Prozessbeendigung | Container tragen Label/Name; Beendigung durch uns über `docker kill/rm` + Job Object. Nicht Teil von OpenHands. |
| R4 Zugangsdaten | `forward_env` mit Wert, `llm.api_key` im Agenten → **nur mit Relay und eigener Umgebung** erfüllbar. |
| R5 Ressourcen | Nur bei je-Konversation-Containern; bei `DockerWorkspace` keine → **eigene Flags**. |
| R11 Image-Herkunft | Standard `latest-python` → **Digest-Pinning und Vorab-Prüfung nötig.** |
| R12 Durchgriffe | Docker-Socket-Mount im geprüften Code nicht gefunden (Suche nach `docker.sock` in den vier Paketen ohne Treffer, Abschnitt 9); `host.docker.internal` aber vorhanden → **entfernen/ersetzen**. |
| R13 Telemetrie | Server-Standard aus (nachgewiesen); Fremdbibliotheken und UI offen/abschaltbar → **Netz zu + OH-12**. |

**Folgerung für die Integration:** OpenHands liefert **keine** der geforderten Isolationsgarantien von sich aus. Es kann nur als **Programm im Inneren einer von JARVIS gebauten Sandbox** mit fester Startvorlage dienen. Dann bleiben als Eigenanteil: Startvorlage, Kopie-hinein/Diff-heraus, Relay, Not-Aus. Ob sich der Agent-Server **ohne Internet** und mit `--read-only`-Wurzel betreiben lässt, ist nur durch den Prototyp klärbar (Q-B, Q-E).

## 8. Empfohlene Schutzmaßnahmen für einen späteren Prototyp (nicht freigegeben)
1. Eigene Startvorlage statt `DockerWorkspace`/Registry-Standard: `--network none` (oder internes Netz nur zum Relay), `--read-only`, `--tmpfs`, `--cap-drop ALL`, `no-new-privileges`, `--user`, `--memory`/`--memory-swap`/`--cpus`/`--pids-limit`, `--init`, `--rm`, kein `--add-host host.docker.internal`, kein Socket, nur Kopie als Mount.
2. Umgebung: `DO_NOT_TRACK=1`, Telemetrie-Exporter `none`, keine `OTEL_*`/`LMNR_*`, `load_public_skills=False`, Critic aus, Browser/ACP/MCP aus; Sitzungsschlüssel gesetzt und zufällig; keine Werte auf der Kommandozeile (Datei-Übergabe oder interne Mechanismen, nicht `-e KEY=Wert`).
3. Image: gepinnter Digest, vorab geholt und geprüft (Prüfdatei nach `docs/INTEGRATIONS.md`), nie `latest`.
4. Laufzeittest mit Netzmitschnitt (OH-05, OH-12) belegt, was tatsächlich nach außen geht; erst dann Aussagen zu Telemetrie und LiteLLM.
5. Strikte Trennung vom echten Projektverzeichnis: Prototyp nur mit Wegwerfkopie in einem eigenen Ordner, keine Zugangsdaten, keine JARVIS-Anbindung.

## 9. Offen / nicht geprüft
- Verhalten der Abhängigkeiten `litellm`, `posthog`, `opentelemetry`, `browser-use`/Chromium-Teile, npm-Pakete zur Laufzeit.
- Gezielter Wiederholungslauf nur auf die vier Quellpakete (ohne Tests): Treffer für `posthog|sentry|segment.io|mixpanel|amplitude|datadog|langfuse|helicone|wandb|logfire|google-analytics|gtag` liegen in `agent_server/telemetry/*`, `agent_server/config.py`, `agent_server/pyproject.toml` sowie in Kommentaren/Regex (Datadog-Erwähnungen in `logging_config.py`, `agent/base.py`, `agent/acp_agent.py`, `mcp/utils.py`; Sentry-Token-Muster in `utils/redact.py:352`). **Es gibt keinen weiteren Sendepfad in diesen Paketen.** Im Frontend-Repository trifft `sentry` nur `automations/detail/script-section.tsx` und ein Seed-Skript (nicht untersucht). Grenze: nur Begriffssuche, keine vollständige Durchsicht.
- Der PostHog-Client ist ein **optionales Extra** (`openhands-agent-server/pyproject.toml:28`: `posthog = ["posthog>=7.82.2,<8"]`) und wird ohne Installation dieses Extras gar nicht importiert (`posthog_exporter.py` lädt ihn träge). `litellm` ist fest eingegrenzt (`openhands-sdk/pyproject.toml:19`: `>=1.104.3,<1.106`). Nachgewiesen.
- `docker.sock`: Suche in den vier Paketen ohne Treffer (Nachweis, dass der Code das Socket nicht einhängt; kein Nachweis für Konfigurationen anderer Nutzer).
- Windows-Verhalten (Pfade, Docker Desktop, WSL-Mounts) – gesamter Prototyp.
- MCP-, Browser- und Tool-Module (`openhands-tools`) nur über Treffer, nicht vollständig gelesen.
