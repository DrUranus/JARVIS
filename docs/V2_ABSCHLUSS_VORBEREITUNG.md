# V2: Abschluss der Vorbereitung (CI-Stand, Merge-Reihenfolge, Container-/VM-Vergleich, OpenHands-Abhängigkeiten)

**Status: Dokumentation. Nichts installiert, ausgeführt oder verdrahtet; kein Merge.** Stand 2026-11-11, `main` = `7cc65b0e9fcd` (V1-Freeze, unverändert). V1-Windows-Abnahme **#186 bleibt oberste Priorität**; bis dahin wird nichts gemergt. PermissionEngine, X0, Not-Aus, Audit und Sicherheitsdefaults sind unberührt. Fasst `docs/V2_SANDBOX_VORSCHLAG.md`, `docs/V2_OPENHANDS_SICHERHEITSBERICHT.md` und `docs/V2_LIZENZPRUEFUNG_PRIVAT.md` zusammen und ergänzt sie.

## 1. CI-Status aller V2-Draft-PRs (GitHub-Runner, ohne Mensch)
| PR | Branch | Inhalt | tests-linux | tests-windows | Weitere |
|---|---|---|---|---|---|
| #229 | `claude/v2-foundation` | Architektur, Backlog, OSS-Bewertung, V2-01 `credibility.py` | grün | grün (5270 bestanden / 46 übersprungen) | real-browser (Ubuntu/Windows), GUI/Voice/Not-Aus grün |
| #230 | `claude/v2-02-plan-eval` | Plan-Evaluationsharness + Mock-LLM (nur Tests) | grün | grün | GUI/Voice/Not-Aus grün |
| #231 | `claude/v2-phase-a-docs` | Phase-A-Dokumente (Basis: `claude/v2-foundation`) | **keine CI** (Basis ≠ main) | **keine CI** | – |
| #232 | `claude/v2-docs-mcp` | MCP-Sicherheit, Prüfdatei | grün | grün | |
| #233 | `claude/v2-docs-pypdf` | Prüfdatei pypdf | grün | grün | |
| #234 | `claude/v2-docs-sandbox` | Sandbox-Vorlage Windows 11 Home | grün | grün | |
| #235 | `claude/v2-03-project-context` | V2-03 Projektkontext (lesend, unangebunden) | grün | grün | GUI/Voice/Not-Aus grün |
| #236 | `claude/v2-docs-04-06` | V2-04 Variantenvergleich, V2-06 Artefaktkonzept | grün | grün | |
| #237 | `claude/v2-docs-openhands-security` | OpenHands-Sicherheitsbericht | grün | grün | |
| #238 | `claude/v2-docs-lizenzen` | Lizenzprüfung (privat) | grün | grün | |
| diese Datei | `claude/v2-docs-abschluss` | Abschlussdokument | wird mit dem PR gestartet | wird mit dem PR gestartet | |

**Fehler:** keine. **Übersprungene Tests:** `suite (...)` und `phase 15 gezielt` zeigen „skipped“ (laufen nur bei manuellem Start). In `tests-windows` von #229: 46 Skips, itemisiert in `docs/V2_04_CI_VERGLEICH.md` §7 (u. a. 13 POSIX-Symlink-Tests mit Windows-Ersatz, 11 X11, 7 Playwright im Job `tests-windows` mit Ersatz im Job `real-browser`, 5 POSIX-Shell, 2 `JARVIS_NATIVE_GUI` = interaktive Abnahme #186, 2 echte Windows-Lücken: `test_office.py:411` Symlink-Recht und `test_self_improvement_workspace.py:451` `/proc`-Nachfahrenerkennung). Die reinen Dokument-PRs ändern keinen Code; ihre Windows-Läufe sind deshalb inhaltlich die gleiche Suite. **Hinweis:** Die Skip-Listen der übrigen Läufe wurden nicht einzeln neu ausgewertet. Runner-CI ersetzt nicht die interaktive Abnahme #186.

## 2. Branch-Abhängigkeiten und Merge-Reihenfolge
**Befunde (nachgewiesen):**
- Alle Branches außer #231 gehen von `main` `7cc65b0` aus; **#231 ist auf `claude/v2-foundation` (#229) gestapelt.**
- Geänderte Dateien (aus `git diff --name-status`): die Dateimengen sind **paarweise disjunkt**, mit einer Ausnahme: `docs/V2_BACKLOG.md` wird in #229 angelegt und in #231 ergänzt (gewollte Stapelung). `docs/TESTING.md` wird nur in #229 geändert.
- **Trial-Merge** (lokal, in einem Wegwerf-Worktree, nichts gepusht): alle zehn Branches (#229, #231, #230, #235, #232, #233, #234, #236, #237, #238) ließen sich in dieser Reihenfolge **ohne Konflikt** zusammenführen; danach liefen `test_research_credibility`, `test_plan_eval`, `test_project_context`, `test_integration_docs`, alle `test_*security*` und `test_emergency_stop` **ohne Fehlschlag** (Linux; 23 erwartete Windows-Skips). Das ist kein Windows-Nachweis.
- Weiche Abhängigkeiten (nur Dokumentverweise, keine Tests): #234 verweist auf `V2_OPEN_SOURCE_BEWERTUNG.md` und `V2_BACKLOG.md` (#229) sowie `V2_OPENHANDS_SICHERHEITSBERICHT.md` (#237); #237 verweist auf `V2_SANDBOX_VORSCHLAG.md` (#234); #236 verweist auf `V2_PHASE_A.md` (#231) und `V2_BACKLOG.md` (#229); #238 und dieses Dokument verweisen auf #234/#237. Code (#235, #230, `credibility.py`) hat **keine** Abhängigkeit untereinander und wird von keinem Produktivmodul importiert (Layering-Tests).

**Vorbedingungen für jeden Merge (Besitzer):** (1) V1-Abnahme #186 abgeschlossen und der Freeze ausdrücklich aufgehoben; (2) CI des betreffenden PR auf aktuellem Stand grün (nach jeder Änderung neu); (3) Review durch den Besitzer; (4) PR vom Entwurf auf „bereit“ durch den Besitzer. Es erfolgt **kein** automatischer Merge.

**Empfohlene Reihenfolge**
1. **#229** (Basis, enthält den einzigen Produktivdatei-Eintrag `research/credibility.py`, unverdrahtet).
2. **#231:** erst nach Merge von #229 die Basis auf `main` umstellen, CI abwarten, dann mergen (vorher hat #231 keine CI).
3. **#230** (nur Tests), danach **#235** (unverdrahtetes Modul). Beide unabhängig; die Reihenfolge ist nur eine Empfehlung, weil der Harness für spätere Anbindungen genutzt werden soll.
4. Dokumente in Verweisrichtung: **#238** (Lizenz), **#234** (Sandbox), **#237** (Sicherheitsbericht), **#232** (MCP), **#233** (pypdf), **#236** (V2-04/06), dieses Abschlussdokument zuletzt.
5. Nach jedem Merge die Basis der übrigen offenen PRs prüfen; PRs, deren Basis sich ändert, laufen neu (CI-Kosten: Windows rund 22 bis 28 Minuten je Lauf).
**Nicht** zusammenfassen und **nicht** in einen Sammel-PR umbauen (Squash/Konflikte aus früherer Erfahrung vermeiden). Pushes auf offene Branches vermeiden, bis die Merges beginnen (jeder Push startet die Windows-CI neu).

## 3. Container-Kandidat Rancher Desktop gegen eigenständige Linux-VM (Windows 11 Home)
Quellen Rancher: `docs.rancherdesktop.io` (Latest 1.25), GitHub-Release `v1.25.0`, Microsoft `wsl-config` (2026-10-16). „nicht dokumentiert“ = auf den gelesenen Seiten nicht gefunden.

### 3.1 Rancher Desktop – Befunde
| Punkt | Befund |
|---|---|
| Lizenz | Apache-2.0 (`LICENSE` gelesen) |
| Windows 11 Home | **ausdrücklich unterstützt** („Windows 11 (including Home edition) with latest updates“); WSL muss vorher installiert sein; Virtualisierung nötig; empfohlen **8 GB RAM, 4 CPU**; Mindestplatte nicht dokumentiert |
| Rechte | Installation braucht Admin („an Admin's intervention is required“); „Privileged Service“ nötig, um Dienste auf anderen Schnittstellen als 127.0.0.1 anzubieten; Admin zur Laufzeit nicht dokumentiert |
| Architektur | WSL 2; Distributionen `rancher-desktop` und `rancher-desktop-data`; **„For Windows, all files are automatically shared via WSL2“**; Isolationsgrenze **nicht dokumentiert**; ob `/mnt/c` in der Distribution eingehängt ist, **nicht dokumentiert** (Standard von WSL: Automount an, laut Microsoft) |
| Engine | wählbar: containerd + nerdctl oder dockerd (moby); Standard unter Windows **nicht dokumentiert** (Beispielausgaben widersprechen sich); Docker-Socket/Named Pipe unter Windows **nicht dokumentiert** |
| Kubernetes | **standardmäßig an**, abschaltbar (`rdctl set --kubernetes.enabled=false`) |
| Netz | Standard-Containernetz **nicht dokumentiert**; `host.docker.internal` und `host.rancher-desktop.internal` verfügbar (dokumentiert); **Egress-Begrenzung nicht dokumentiert**; Ports ohne Privileged Service nur auf localhost; Ingress-Standard `localhostOnly=false`; Sicherheitsfix in 1.25: unter dem Netzwerkmodus „consomme“ waren auf 127.0.0.1 veröffentlichte Ports von anderen Rechnern erreichbar |
| Ressourcen | VM-Speicher/CPU über `.wslconfig` **global für alle WSL-2-Distributionen** (Microsoft); Rancher-Seite „Hardware“ nur für macOS/Linux; Container-Limits über Docker-/nerdctl-Flags (nicht in Rancher-Docs beschrieben) |
| Telemetrie/Netz | Einstellung „Allow collection of anonymous statistics“ (`application.telemetry.enabled`; Beispielwert `true`, Windows-Standard nicht dokumentiert); automatische Updates (`application.updater.enabled`); Update-Prüfung `desktop.version.rancher.io/v1/checkupgrade`; beim ersten Start/Versionswechsel Downloads von k3s (`github.com`, `api.github.com`), kubectl (`storage.googleapis.com`); Datenschutzseite von SUSE nicht erreichbar (404) |
| Sicherheit | kein Härtungsleitfaden, kein Rootless-Hinweis; Funktionen: „Allowed Images“ (begrenzt nur Image-Pulls), Deployment-Profile (Registry-Schlüssel, „Locked“-Einstellungen); Meldeweg `security-rancher@suse.com` |
| Automatisierung | `rdctl` (start, shutdown, set, list-settings, reset, snapshot, shell, api), **als experimentell bezeichnet**; Start ohne Fenster per `--application.start-in-background`; **vollständig kopfloser Betrieb nicht dokumentiert**; die Anwendung muss für `set`/`shutdown` laufen |
| Version | v1.25.0, Docker 29.9.3, nerdctl 2.2.2 gebündelt |

### 3.2 Gegenüberstellung
| Kriterium | Rancher Desktop (WSL 2) | Eigenständige Linux-VM (VMware Workstation / VirtualBox, optional Docker Engine darin) |
|---|---|---|
| Isolationsgrenze | Container im Kernel der WSL-2-VM; WSL-Distributionen teilen den Kernel; keine Herstelleraussage zu einer Sicherheitsgrenze | **eigener Kernel, eigene Platte und eigenes Netz**; stärker (Einschätzung) |
| Host-Dateien | „All files shared via WSL2“ – Windows-Laufwerke sind standardmäßig erreichbar, müssen aktiv abgeschaltet werden (`automount.enabled=false`, Übertragbarkeit auf Rancher-Distributionen **ungeprüft**) | kein gemeinsamer Ordner (VirtualBox: nur nach Einrichtung; Übergabe per Archiv, Mechanismus offen) |
| Netz | kein dokumentierter Egress-Filter; `--network none` lässt sich als Docker-Standardflag setzen, ist aber auf den Rancher-Seiten **nicht beschrieben** und bleibt Prototyp-Test | virtuelles Netz **ohne** Außenadapter (VirtualBox: internes/Host-only-Netz; NAT erreicht den Host-Loopback), Relay am Host |
| Zugangsdaten | wie beim Container: nur über Relay | frische VM, kein Host-SSO |
| Ressourcen | WSL-global (alle Distributionen) | feste VM-Größe (vCPU, RAM, Datei als Platte) |
| Prozess beenden / Not-Aus | `rdctl shutdown` (experimentell), `docker kill/rm` | `VBoxManage controlvm poweroff` bzw. `vmrun`; Snapshot-Rücksetzen |
| Windows-Home-Eignung | ausdrücklich genannt | VirtualBox/VMware: Home nicht ausdrücklich genannt; VirtualBox neben aktiver Windows-Hypervisor-Plattform (WSL 2) laut Handbuch mit Leistungsproblemen; VMware nennt WSL-2-Koexistenz |
| Lizenz (privat) | Apache-2.0 | VMware: laut Ankündigung kostenlos (Lizenztext nicht lesbar); VirtualBox GPLv3, Extension Pack nur privat/Bildung |
| Wartung/Bedienung | App aktualisiert sich (Updater, Netzzugriff nötig); GUI + CLI | Gastsystem selbst pflegen; mehr Aufwand |
| Telemetrie/Netzzugriffe | Statistik-Einstellung, Update-Prüfung, k3s-Downloads | VM-Software selbst (VMware/VirtualBox) nicht untersucht |
| Zusätzliche Angriffsfläche | Privileged Service, `host.docker.internal`, Kubernetes (Standard an) | Hypervisor, Gast-Updates |

### 3.3 Einordnung (Einschätzung, nicht belegt)
- Rancher Desktop löst die **Lizenz- und Home-Frage** besser als Docker Desktop, löst aber **nicht** die Isolationsfrage: die WSL-2-Grenze bleibt dieselbe, und Netz- und Dateisperren müssen wir selbst setzen und testen (OH-01 bis OH-12).
- Die VM ist die **stärkere Grenze**, aber aufwendiger und auf Home/WSL-Koexistenz zu prüfen. Beide Wege behalten Kopie-hinein/Diff-heraus.
- **Empfehlung für den nächsten freigegebenen Schritt:** keine Installation. Erst Hardwareangaben (CPU, RAM, Platte, BIOS-Virtualisierung) und Freigabe eines **Wegwerf-Prototyps** (Rancher Desktop mit Kubernetes aus und gehärtetem Container ohne Netz) durch den Besitzer; VM als Ausweichvariante, wenn der Container Netz-/Dateitests nicht besteht oder sensiblere Repositories bearbeitet werden. Beide Wege brauchen Prüfdateien nach `docs/INTEGRATIONS.md` (Hash, Pflege, Sicherheitsstatus, Windows-Nachweis) vor der Installation.

## 4. OpenHands-Abhängigkeiten: `browser-use`, `posthog`, `lmnr` (statisch, Quelltext gelesen)
Methode: die Quellarchive der im `uv.lock` festgelegten Versionen (`browser-use 0.11.9`, `posthog 7.82.2`, `lmnr 0.7.60`) wurden von PyPI geladen (SHA-256 gegen die Registry geprüft), **nur entpackt und gelesen**, nicht installiert und nicht ausgeführt. Lizenzen laut Dateien/Metadaten: `browser-use` MIT (LICENSE gelesen), `posthog` MIT, `lmnr` Apache-2.0. Pfade relativ zum jeweiligen Archiv; „OH“ = `software-agent-sdk/openhands-tools/openhands/tools/browser_use/`.

### 4.1 Nachgewiesene Telemetrie- und Netzpfade
| Befund | Fundstelle |
|---|---|
| **`browser-use` hat eine eigene PostHog-Telemetrie, standardmäßig AN**: `ANONYMIZED_TELEMETRY` Standard `true`; Projektschlüssel fest im Code, Host `https://eu.i.posthog.com` | `browser_use/config.py:58-59`, `browser_use/telemetry/service.py:31-33` |
| Der Client wird mit **`enable_exception_autocapture=True`** und **`disable_geoip=False`** erzeugt | `browser_use/telemetry/service.py:46-51` |
| `posthog` hängt bei aktivierter Exception-Autocapture **`sys.excepthook` und `threading.excepthook`** um; unbehandelte Ausnahmen (mit Traceback) gehen an PostHog | `posthog/exception_capture.py` (Konstruktor setzt beide Hooks); Standard der Bibliothek selbst `False` (`posthog/client.py:704`), hier aber von `browser-use` auf `True` gesetzt |
| Ein dauerhafter Gerätebezeichner wird in `BROWSER_USE_CONFIG_DIR/device_id` angelegt und als Nutzer-ID verwendet | `browser_use/telemetry/service.py:37,95-114` |
| **`BROWSER_USE_CLOUD_SYNC` übernimmt standardmäßig den Wert von `ANONYMIZED_TELEMETRY`** (also an); Cloud-API-Standard `https://api.browser-use.com` | `browser_use/config.py:62-69` |
| Agent-Ereignisse enthalten **Aufgabentext, besuchte URLs, Aktionsverlauf, Endergebnis, Fehlertext, Modell/Provider, Token-/Dauer-Zahlen** | `browser_use/telemetry/views.py:25-60` (`AgentTelemetryEvent`); Versand aus `browser_use/agent/service.py:2141` (nur bei Nutzung der Klasse `Agent`) |
| **OpenHands erzeugt den Telemetrie-Client trotzdem:** `CustomBrowserUseServer` erbt von `LogSafeBrowserUseServer = server.BrowserUseServer`; `BrowserUseServer.__init__` ruft `ProductTelemetry()` | OH `server.py:17,24`, OH `logging_fix.py:134,145`, `browser_use/mcp/server.py:187,201`; ebenso `browser_use/tools/registry/service.py:37` |
| OpenHands setzt **kein** `ANONYMIZED_TELEMETRY`, `BROWSER_USE_CLOUD_SYNC` oder `BROWSER_USE_DISABLE_EXTENSIONS` | Suche über `openhands-tools` (kein Treffer) |
| `browser-use` lädt beim Browserstart **vier Standard-Erweiterungen** (u. a. uBlock Origin, Cookie-Handling, ClearURLs) vom Chrome-Update-Server `clients2.google.com` und legt sie im Cache ab, solange `BROWSER_USE_DISABLE_EXTENSIONS` nicht gesetzt ist | `browser_use/browser/profile.py:16-23,601,936-1000` |
| `lmnr` (Laminar): Standardziel `https://api.lmnr.ai`, Schlüssel aus `LMNR_PROJECT_API_KEY`, Abschalter `LMNR_DISABLE_TRACING`; Inhalte werden standardmäßig mitgeschrieben (`LMNR_TRACE_CONTENT` Standard `true`) – **wirksam erst, wenn Laminar initialisiert wird**; OpenHands initialisiert nur bei gesetzten Umgebungsvariablen | `lmnr/opentelemetry_lib/tracing/exporter.py:49,58`, `…/processor.py:225`, `…/instrumentation/openai/utils.py:142`; OH-SDK `observability/laminar.py:28,345` |
| `browser-use` nutzt `lmnr` nur als optionale Beobachtung (No-op ohne Installation) | `browser_use/observability.py` |
| `posthog`-Bibliothek selbst sendet nur bei `capture()`/Hooks; sie startet Consumer-Threads im Hintergrund; ein Poller für Feature-Flags nur unter bestimmten Bedingungen (nicht abschließend geprüft) | `posthog/client.py` (Consumer, Poller) |

### 4.2 Folgerungen
1. **Beim Browser-Werkzeug von OpenHands ist ohne Gegenmaßnahme eine fremde Telemetrie aktiv** (statisch belegt): Posthog-Client mit Hook auf unbehandelte Ausnahmen, Cloud-Sync-Standard „an“ und Gerätekennung. Ob dabei Ereignisse mit Inhalten tatsächlich gesendet werden, hängt davon ab, welche `browser-use`-Klassen OpenHands aufruft; die `Agent`-Ereignisse (mit Aufgabentext und URLs) entstehen nur bei Nutzung der Klasse `Agent`, die OpenHands nach Importen nicht verwendet (nur `BrowserSession`, `DomService`, MCP-Server-Klasse). **Die Exception-Autocapture ist aber unabhängig davon aktiv.**
2. Gegenmaßnahmen (Wirksamkeit **nicht verifiziert**): `ANONYMIZED_TELEMETRY=false`, `BROWSER_USE_CLOUD_SYNC=false`, `BROWSER_USE_DISABLE_EXTENSIONS=true`, `DO_NOT_TRACK=1`, `LMNR_DISABLE_TRACING=true`, keine `LMNR_*`/`OTEL_*`, **Browser-Werkzeug aus**, und vor allem **Netz zu**.
3. Das Browser-Werkzeug sollte im Prototyp **nicht** aktiviert werden; für ein Coding-Ziel ist es nicht erforderlich.

### 4.3 Ungeprüft
- Laufzeitverhalten (tatsächliche Verbindungen; Netz-Mitschnitt nötig, OH-12).
- Weitere Abhängigkeiten der 415 Pakete (Lizenzen, Telemetrie), `litellm`, Chromium/Playwright, `mcp`/`fastmcp`.
- Ob `posthog`-Poller oder weitere Hooks beim Import ausgeführt werden.
- Weitere Netzwege in `openhands-tools` (`gemini`, `ask_oracle`, Terminal-Befehle des Agenten selbst).

## 5. Offene Sicherheitsfragen
1. Netzweg Worker → Relay ohne weiteren Ausgang (Q-A) und Betrieb des Agent-Servers ohne Internet (Q-B).
2. Verhalten der Abhängigkeiten ohne Netz (Telemetrie-Hooks, Updates, Extension-Downloads) (Q-C, OH-12).
3. Nutzbarkeit einer eigenen festen Startvorlage statt `DockerWorkspace`/Registry-Standard (Q-D) und Schreibpfade bei `--read-only` (Q-E).
4. Rancher: Standard-Engine unter Windows, Named Pipe, Mount von Windows-Laufwerken in die Distribution, Standard der Statistik-Einstellung, `--network none`-Verhalten.
5. WSL-Grenze als Sicherheitsgrenze: keine Herstelleraussage; Netz-/Ressourcen-Einstellungen sind global.
6. Lizenz: die 415 Abhängigkeiten, VMware-Lizenztext, Windows-Lizenz für WSL ungeprüft.
7. Authentifizierung des Agent-Servers (ohne Sitzungsschlüssel offen) – nur mit gesetztem Schlüssel und Loopback betreiben.

## 6. Voraussetzungen für die spätere OpenHands-Integration (alle erfüllen, vorher keine Installation)
1. V1-Abnahme #186 abgeschlossen; ausdrückliche Freigabe des Besitzers für Installation und Ausführung eines **Wegwerf-Prototyps** (getrennt von JARVIS und vom echten Projektverzeichnis).
2. Hardwareangaben des Besitzers (CPU, RAM, freier Speicher, BIOS-Virtualisierung) und Entscheidung Container (Rancher Desktop) oder VM.
3. Prüfdateien nach `docs/INTEGRATIONS.md` für die gewählte Laufzeit (Rancher Desktop bzw. VM-Software) und für das Image (Digest-Pinning, kein `latest`); Lizenzprüfung der Abhängigkeiten.
4. Prototyp-Nachweise: Abnahmetests T1–T13 (`docs/SANDBOX_DESIGN.md`) und OH-01 bis OH-12 (`docs/V2_SANDBOX_VORSCHLAG.md`), insbesondere Netz-Mitschnitt (OH-05, OH-12) und „kein Schlüssel im Worker“ (OH-03).
5. Eigene feste Startvorlage (kein Netz außer Relay, `--read-only`, Caps leer, `no-new-privileges`, Limits, Kopie als Mount, kein `host.docker.internal`), `load_public_skills=False`, Critic aus, Browser/ACP/MCP aus, Telemetrie-Schalter wie in 4.2.
6. Host-LLM-Relay (Schlüssel bleibt auf dem Host, Budget, Protokoll, Not-Aus).
7. Ablauf: Bestätigung pro Lauf über `ToolRegistry.execute` → `PermissionEngine`; Diff wird auf dem Host aus der Kopie berechnet, mit `PathGuard` geprüft, nie automatisch übernommen; Not-Aus beendet Worker vollständig.
8. Separate Besitzerfreigabe für die Verdrahtung (nur in `bootstrap.py`), die Dokumentation der Lizenz-/Sicherheits-/Kompatibilitätsprüfung (Entscheidung 4 der früheren Vorgaben) und **ein Windows-CI-Nachweis** soweit automatisierbar; sonst als „manuell, nicht automatisiert“ gekennzeichnet.
Bis alle Punkte erfüllt sind, bleibt **Coding bei der vorhandenen JARVIS-Implementierung**.

## 7. Entscheidungen des Besitzers (offen)
CPU/RAM/Platte/BIOS-Angaben · Container (Rancher Desktop) oder VM als erster Prototyp · Freigabe eines Wegwerf-Prototyps (Installation) nach #186 · Freigabe weiterer reiner Dokumentationsprüfungen (z. B. Lizenzen der 415 Abhängigkeiten, Quellcode `litellm`) · Merge-Zeitpunkt und -Reihenfolge nach Abschnitt 2.
