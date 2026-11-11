# Sandbox-Entscheidungsvorlage: isolierter Coding-Worker (OpenHands) – Windows 11 Home

**Status: Vorlage zur Besitzerentscheidung. Nichts ist installiert, ausgeführt, verdrahtet oder freigegeben.** OpenHands bleibt Integrationskandidat ohne Installations- oder Ausführungsfreigabe; **Coding bleibt vorerst bei der vorhandenen JARVIS-Implementierung** (`coding/`, `self_repair/`, `self_improvement/`). Stand: 2026-11-11 (zweite Fassung, ersetzt die erste). Besitzerbestätigung: **der JARVIS-PC läuft mit Windows 11 Home.** Grundlage bleiben `docs/SANDBOX_DESIGN.md` (R1–R9, T1–T13) und `docs/INTEGRATIONS.md`. Release-Freeze und V1-Abnahme #186 haben Vorrang; PermissionEngine, X0, Not-Aus und Audit bleiben unverändert.

**Kennzeichnung:** *dokumentiert* = auf der genannten Herstellerseite gelesen; *nicht dokumentiert* = auf den gelesenen Seiten nicht gefunden (kein Beleg für „sicher“); *Einschätzung* = meine Bewertung, kein Herstellersatz. Quellen in Abschnitt 11. Teile der Docker-Referenz wurden nur als Zusammenfassung gelesen und sind markiert.

## 1. Kurzfassung der Empfehlung für Windows 11 Home
1. **Hyper-V entfällt** als Standardlösung (Microsoft: Windows 11 Pro, Enterprise, Education; Home nicht aufgeführt).
2. **Docker Desktop mit WSL 2** ist als Prototypkandidat zulässig, aber mit zwei Vorbehalten: (a) die aktuelle Docker-Systemanforderungsseite führt **Windows 11 Home nicht auf** (Pro/Enterprise/Education); ob Installation auf Home funktioniert, ist praktisch zu prüfen, nicht zu unterstellen; (b) die WSL-Grenze ist **schwächer als eine VM-Grenze** (siehe 5).
3. **Stärkere Isolation auf Home** bietet eine **eigene Linux-VM** über VMware Workstation (kostenlos seit 2024-11), VirtualBox oder QEMU/WHPX; sie ist aber aufwendiger, die Zusammenarbeit mit WSL 2 ist teils eingeschränkt, und die Automatisierung ist nicht belegt (Abschnitt 5).
4. **Ja, OpenHands kann nach heutigem Wissensstand nur dann „vollständig isoliert mit Rückgabe kontrollierter Diffs“ laufen, wenn JARVIS den Rahmen selbst baut** (Kopie hinein, Diff aus der Kopie heraus, kein Netz außer LLM-Relay). OpenHands dokumentiert diesen Betriebsmodus **nicht** (Abschnitt 7).
5. **Vorläufige Empfehlung:** Stufenplan. Zuerst weitere reine Dokumentationsklärung und Besitzerprüfung der Hardware (Abschnitt 9). Dann (mit eigener Freigabe) ein **Wegwerf-Prototyp in einem Container** (Docker, gehärtet) ohne JARVIS-Anbindung, nur mit Kopie-hinein/Diff-heraus und ohne Geheimnisse. **Ein VM-Prototyp (VMware oder VirtualBox) ist die stärkere Zielvariante**, wenn die Container-Variante die Tests nicht besteht oder sensiblere Repositories bearbeitet werden sollen. Produktive Nutzung erst nach bestandenen Abnahmetests und Windows-Nachweis.

## 2. Befunde zu OpenHands (Q1–Q4, nur Dokumentation)
| Frage | Befund | Beleg |
|---|---|---|
| **Q1 Wo läuft die Modellschleife?** | Im **Agent-Server innerhalb von Container/Pod**: „it runs the agent loop and its own tools inside the container“ (Docker-Modus je Konversation). Ohne Container laufen „Agent Server and tools … directly on the backend host without container isolation“. Kommunikation REST + WebSocket, Sitzungsschlüssel im Header, Standard-Bindung an 127.0.0.1. Die Docker-Sandbox des SDK nutzt `RemoteConversation` über WebSocket (Standardport 8010). | Doku Agent-Server, Docker-Ausführung, SDK Docker-Sandbox |
| Betrieb ohne Internet, LLM über Host-Endpunkt | `base_url` des LLM ist konfigurierbar (Beispiele lesen `LLM_BASE_URL`). **Ein Offline-Betrieb ist nicht dokumentiert**; Netzwerkmodus/Egress-Filter ebenfalls **nicht dokumentiert**. Der Container bekommt `host.docker.internal` auf das Host-Gateway. | Doku Docker-Ausführung, SDK |
| **Q2 Datenabfluss** | LLM-Anbindung über **LiteLLM** („any LLM supported by LiteLLM“). Datenschutzerklärung (Stand 2025-09-03) betrifft die gehosteten Dienste: Eingaben/Code können an KI-Drittanbieter gehen. Ob sie für Selbstbetrieb gilt, **nicht dokumentiert**. Weitere Abrufe: Skills-Sync aus GitHub (`OpenHands/extensions`), Abruf von `ghcr.io/openhands/agent-server:latest-python`, Browser-Werkzeug (reale Webseiten). Suche, MCP, GitHub-Integration, Paketinstallation: **nicht gelesen/nicht dokumentiert**. | Datenschutz, SDK-README, Doku |
| **Q3 Telemetrie** | Datenschutzerklärung nennt Drittanbieter-Analyse („Posthog, Google Analytics or similar“) für Website/Dienste; „Do Not Track“ wird nicht beachtet. **Abschalt-Variablen und Startverbindungen des Selbstbetriebs: nicht dokumentiert.** Quellcode nicht geprüft (nur mit lokalem Klon und Suche belegbar, braucht Download, daher hier nicht erfolgt). | Datenschutz, Doku |
| **Q4 Begrenzung** | Docker-Modus **dokumentiert:** läuft als Host-UID/GID statt root; `--cap-drop ALL`; `no-new-privileges`; Standardgrenzen 4 GB RAM, 2 CPUs, 512 Prozesse, Leerlauf-Ende 1200 s (Hinweis der Doku: Grenzen vom Client angeforderte Werte werden nicht gedeckelt). Mounts: Konversationsordner, `.openhands`, **`/workspace` mit Lese- und Schreibzugriff auf das Host-Verzeichnis**; ein Nur-Lesen-Modus, Egress-Begrenzung, Umgebungsdurchreichung und Docker-Socket-Verhalten sind **nicht dokumentiert**. Geheimnisse: Secret Registry maskiert Werte in Ausgaben; gespeichert verschlüsselt mit `OH_SECRET_KEY`. Die Beschreibung der Docker-Sandbox als „complete isolation from the host system“ widerspricht dem eigenen Hinweis „the agent will be able to access any project under PROJECTS_PATH“ bzw. dem Schreibzugriff auf `/workspace`. | Doku Docker-Ausführung, Secrets, Sicherheit |
| Ergebnisrückgabe | Es gibt Endpunkte für Git-Diff (`modified`/`original` je Datei). **Ein Betriebsmodus, der den Host-Arbeitsordner unberührt lässt und nur einen Patch liefert, ist nicht dokumentiert.** | SDK API-Referenz |
| Eigene Risikoaussagen | Standard-Bestätigungsrichtlinie „ConfirmRisky“; das Risiko einer Aktion stammt vom LLM selbst, nicht von einer unabhängigen Prüfung. | Doku Sicherheit |

**Folgerungen (Einschätzung):** (1) Die Schleife sitzt im Worker, deshalb braucht der Worker einen Weg zum Modell; ohne Relay/lokales Modell kann er keine Netzsperre haben. (2) Die Standard-Mounts sind für uns ungeeignet (Host-Verzeichnis lesbar/schreibbar); die Isolation muss JARVIS durch **eigene feste Startvorlage** erzwingen, nicht durch OpenHands-Einstellungen. (3) Der Standard-Image-Tag `latest-python` verstößt gegen R11 (Digest-Pinning). (4) Ausgehende Abrufe (Skills-Sync, Image-Pull) müssen durch Netzsperre verhindert werden; wie sie sich in OpenHands abschalten lassen, ist nicht dokumentiert. (5) Die Telemetriefrage ist **nicht beantwortbar ohne Quellcode-Prüfung**; bis dahin gilt „Netz zu“ als einzige belastbare Gegenmaßnahme.

## 3. Lizenz Docker Desktop (Docker Subscription Service Agreement, „Last updated on August 26, 2026“)
- **Private, nichtkommerzielle Nutzung:** „Developer Use“ ist auf einen einzelnen Entwickler in persönlicher, nichtkommerzieller Eigenschaft beschränkt und bezieht sich auf „Open Source Software or free applications“ (dokumentiert). Ein **privates, nicht quelloffenes Hobbyprojekt** ist damit **nicht eindeutig** abgedeckt (Auslegungsfrage).
- **Gewerbliche Nutzung:** kostenlos nur für Unternehmen mit **weniger als 250 Beschäftigten und weniger als 10 Mio. US-$ Umsatz** (Vertragstext verlangt beide Schwellen; die Docker-Installationsseite formuliert „OR“ – Abweichung), Behörden immer kostenpflichtig. **Nutzung im Zusammenhang mit einer Anstellung/Beauftragung durch ein Unternehmen ist nicht „Developer Use“.** Was als „commercial use“ gilt, ist **nicht definiert**; ein freiberuflicher Einzelner ist nicht ausdrücklich geregelt.
- **Folge:** Für den Privatgebrauch plausibel kostenlos, für Gewerbliches Klärung mit Docker nötig. Das ist eine **juristische Frage des Besitzers**, keine technische.
- **Alternative ohne Desktop:** Docker Engine selbst steht laut Installationsseite unter **Apache License 2.0** (Zuordnung der Zeile zur Engine nicht ausdrücklich bestätigt), die Desktop-Bedingungen scheinen nicht zu gelten, **ausdrücklich bestätigt wird das nirgends**. Engine in einer eigenen WSL-Distribution (`apt install docker-ce`) wäre eine Option, aber eine Koexistenz mit Docker Desktop in derselben Distribution verursacht laut Doku Konflikte.

## 4. Hardware- und Virtualisierungsanforderungen
| Variante | Dokumentierte Anforderungen | Nicht dokumentiert |
|---|---|---|
| Docker Desktop (WSL 2) | 64-Bit-CPU mit SLAT, **8 GB RAM**, Virtualisierung im BIOS/UEFI, WSL ≥ 2.1.5 (für Enhanced Container Isolation ≥ 2.6), Windows 11 „Enterprise, Pro oder Education 23H2 (22631) oder höher“ – **Home nicht aufgeführt**; Hinweis: „Windows Home or Education editions only allow you to run Linux containers“ | Plattenbedarf; Home-Unterstützung der WSL-2-Variante |
| WSL 2 | Virtual Machine Platform (auf Home verfügbar, Microsoft-FAQ), Virtualisierung im BIOS; Standard: **50 % des RAM**, alle Prozessoren, Swap 25 % des Speichers | BIOS-Bezeichnung, Mindest-RAM/-Platte |
| OpenHands-Container | Standardgrenzen 4 GB RAM, 2 CPUs, 512 Prozesse | tatsächlicher Bedarf, Plattenbedarf |
| VirtualBox | SSE2 für den Host; bis 32 vCPUs je VM | RAM/Platte-Empfehlungen; **Home ausdrücklich genannt: nicht dokumentiert** |
| VMware Workstation | kostenlos für alle Nutzer seit 2024-11-11 (kommerziell, privat, Bildung; kein Support) | Systemanforderungen, Home-Unterstützung, **aktuelle Lizenzseite nicht abrufbar (404)** |
| QEMU (WHPX) | Windows Hypervisor Platform; x86_64 getestet ab Windows 10 2004 | Home ausdrücklich; Automatisierung im gelesenen Text |

**Einschätzung (nicht belegt):** Für Docker/WSL 2 plus Agentenlauf sind **mindestens 16 GB RAM** und mehrere zehn GB freier Platz sinnvoll; das ist zu messen. Der Besitzer sollte Prozessor, RAM, freien Speicher und den Status von Virtualisierung (Task-Manager → Leistung → CPU) mitteilen.

## 5. Vergleich der Optionen für Windows 11 Home
| Kriterium | **O1 Docker Desktop (WSL 2), gehärteter Container** | **O1b Docker Engine in eigener WSL-Distribution** | **O2 Linux-VM (VMware Workstation oder VirtualBox)** | O3 QEMU/WHPX-VM | Ausgeschlossen |
|---|---|---|---|---|---|
| Isolationsgrenze | Container im Kernel der WSL-2-VM; WSL-Distributionen teilen einen Kernel (aus der Architektur ableitbar); Docker selbst: Home-Unterstützung unklar, ECI nur mit WSL ≥ 2.6, Doku: „Use Hyper-V backend for maximum security“ | wie O1, ohne Desktop-Verwaltung | **eigener Kernel, eigene Platte, eigenes Netz**; stärkste auf Home belegbare Grenze (Einschätzung) | wie O2, GPL, kein Komfort | **Hyper-V** (Home nicht aufgeführt), **Windows Sandbox** (laut früherer Prüfung nicht auf Home), **Windows AppContainer** (hoher Eigenbau), **WSL ohne Container** (Netz global, Interop/Mounts standardmäßig an) |
| Windows-Home-Eignung | **ungeklärt** (Docker-Seite) | WSL 2 auf Home dokumentiert | VMware/VirtualBox: Home nicht ausdrücklich bestätigt | WHP-Verfügbarkeit nur indirekt belegt | |
| Zusammenarbeit mit WSL 2 | gleich | gleich | VirtualBox: laut Handbuch **schlechte Leistung**, wenn Hyper-V-Plattform aktiv; Abschalten würde WSL 2 behindern; VMware: laut Microsoft-FAQ ab 15.5.5 mit WSL 2 nutzbar | WHPX nutzt dieselbe Plattform | |
| Host-Dateien | Bind-Mount nur gezielt (eigene Startvorlage); `\\wsl$` erlaubt Windows den Zugriff auf WSL-Dateien; Standard-Automount bei Desktop nicht dokumentiert | `automount.enabled=false` je Distribution dokumentiert | **keine** gemeinsamen Ordner (VirtualBox: standardmäßig keine, Lese-/Schreibmodus wählbar) | keine | |
| Netzwerk | `--network none` (dokumentiert), Relay offen (Q2); `.wslconfig` Netzwerk **global** | wie O1 | VirtualBox: internes Netz oder Host-only; NAT-Standard erreicht Host-Loopback (10.0.2.2) | `-netdev user` | |
| Ressourcen | Container: `--memory`, `--cpus`, `--pids-limit` (dokumentiert); WSL-Grenzen **global** | wie O1 | feste VM-Größe (vCPU bis 32), Platte als Datei | | |
| Prozess beenden / Not-Aus | `docker kill`/`rm` über Label + Job Object um die CLI | wie O1 | `VBoxManage controlvm poweroff` bzw. vmrun (dokumentiert: VBoxManage-Steuerung); Zustand per Snapshot rücksetzbar | QMP (nicht gelesen) | |
| Wartbarkeit | gut (Desktop aktualisiert sich; Image per Digest pinnen) | mittel (Engine selbst pflegen) | **aufwendig** (Gastsystem, Updates, Image) | hoch | |
| Bedienbarkeit | gut | mittel | mittel bis schwer | schwer | |
| Lizenz | Docker-Desktop-Bedingungen (Abschnitt 3) | Apache-2.0 (Engine), Docker Desktop entfällt | VirtualBox: GPLv3; **Extension Pack nur privat/Bildung kostenlos**; VMware: kostenlos, aber Lizenztext ungeprüft | GPLv2 | |

**Einschätzung zur Sicherheit:** Eine eigene VM trennt am besten; der Preis sind Betrieb und Kopplung. Container in WSL 2 sind einfacher, aber die Doku von Docker selbst warnt, dass unter WSL „users can access Docker Engine directly or bypass Docker Desktop security settings“. Für **nicht vertrauenswürdigen Agentencode** ist die VM auf Home die stärkere Wahl, sofern der Aufwand tragbar ist; für den ersten Prototyp mit **Kopie ohne Geheimnisse** genügt die Container-Variante, **wenn** die Tests OH-01 bis OH-12 (Abschnitt 8) bestanden sind.

## 6. Schutzmaßnahmen (gelten für O1/O1b und, sinngemäß, O2)
**Host-Dateien.** Nie das echte Arbeitsverzeichnis einhängen. JARVIS exportiert eine **Kopie** (ohne `.git`, ohne Geheimnisse, ohne Zugangsdaten, nur Dateien, die der Auftrag braucht), die der Worker als eigenes Arbeitsverzeichnis erhält. Alles andere im Container: `--read-only`, `--tmpfs`, `--user` ≠ root. Kein Docker-Socket, kein `--privileged`, keine Geräte, kein Host-Netz. WSL: `automount.enabled=false`, `interop.enabled=false` für eine dedizierte Distribution (dokumentiert; Übertragbarkeit auf die von Docker Desktop verwaltete Distribution **ungeprüft**).
**Netzwerk.** Standard `--network none`. Die Modellschleife im Worker braucht einen einzigen erlaubten Weg zu einem **host-seitigen LLM-Relay** (hält den Schlüssel, Endpunkt-/Modell-Allowlist, Budget, Protokoll, Notaus). Wie dieser eine Weg technisch ohne weitere Ausgänge hergestellt wird, ist **offen (Q-A)**; ohne Lösung kein Start. Skills-Sync, Image-Pull und Browserwerkzeug bleiben dadurch blockiert; das Image wird vorab per Digest geholt und geprüft.
**Zugangsdaten.** Kein API-Schlüssel, kein Token, kein SSO im Worker (R4); der Relay hält den Schlüssel. `OH_SECRET_KEY` und Secret Registry nicht verwenden. Testschlüssel-Suche im Worker nach dem Lauf (OH-03).
**Container-Privilegien.** `--cap-drop ALL`, `no-new-privileges` (Wortlaut der Docker-Referenz nur aus Zusammenfassung, **ungeprüft**), Standard-seccomp unverändert, Benutzer-UID ≠ 0, `--pids-limit`, `--memory` = `--memory-swap`, `--cpus`, `--init`, `--rm`, feste Startvorlage mit Label `jarvis-worker-<Lauf-ID>`; **keine vom Agenten wählbaren Docker-Argumente**. Docker-Desktop-Erweiterungen aus, ECI wenn verfügbar einschalten (Abonnementstufe **nicht dokumentiert**).
**Not-Aus.** Alle Host-Steuerprozesse unter einem Job Object (`self_improvement/winjob.py`, Verdrahtung nur in `bootstrap.py`); Not-Aus und Abbruch: Job beenden, danach Container **namentlich** stoppen/entfernen, Gegenprobe; bei unsauberem Ende „unvollständiger Abbruch“ melden; beim nächsten Start nur lesende Suche nach verwaisten Workern und Rückfrage vor Aufräumen. Der Relay endet zugleich.

## 7. Kann OpenHands „vollständig isoliert“ arbeiten und nur kontrollierte Diffs zurückgeben?
**Antwort (Einschätzung auf Basis der Doku):** *Ja, aber nur durch unseren Rahmen, nicht durch eine OpenHands-Funktion.*
1. JARVIS bestätigt den Lauf (pro Lauf), prüft Isolation (fail-closed) und exportiert die Kopie in ein **eigenes** Verzeichnis.
2. Worker mit fester Vorlage starten (Abschnitt 6); der Agent arbeitet nur in dieser Kopie.
3. Nach Ende/Abbruch hält JARVIS die Kopie an und **berechnet den Diff selbst auf dem Host** (Original gegen Kopie), nicht aus Angaben des Agenten. Der Diff wird als **nicht vertrauenswürdige Daten** behandelt: `PathGuard`, keine Pfade außerhalb, keine Änderungen an Sicherheitsgrenzen, `.github/`, `.claude/`, Konfigurationsstandards; Größen-/Dateianzahlgrenzen; Anzeige im Freigabedialog.
4. Übernahme nur nach Bestätigung, nie automatisch; kein Commit, kein Push.
**Offene Voraussetzungen:** (Q-A) Netzwerkweg nur zum Relay; (Q-B) läuft der Agent-Server ohne Internet; (Q-C) Verhalten bei Telemetrie/Skills-Sync ohne Netz; (Q-D) Kann die SDK-Docker-Sandbox mit unserer festen Startvorlage genutzt werden, oder muss der Agent-Server im Image direkt gestartet werden; (Q-E) Container-Dateisystem bei `--read-only` (Schreibpfade des Agent-Servers). Keines davon ist ohne Ausprobieren belegbar. **Eine „Rückgabe nur von Diffs“ ist daher erst nach Prototyp und bestandenen Tests behauptbar.**

## 8. Abnahmetests
`docs/SANDBOX_DESIGN.md` T1–T13 gelten. Zusätzlich:
| ID | Prüft | Bestanden, wenn |
|---|---|---|
| OH-01 | R11 | falscher/fehlender Image-Digest → Start verweigert; kein `latest`; kein Bau/Pull zur Laufzeit |
| OH-02 | R12 | im tatsächlich wirksamen Start: kein Socket, kein `--privileged`, kein Host-Netz/-PID, Caps leer (Konfiguration wird gelesen) |
| OH-03 | R4 | kein Schlüssel, kein Token in Umgebung/Dateisystem (Testschlüssel-Suche negativ) |
| OH-04 | R10 | Relay erlaubt nur konfigurierten Endpunkt/Modell, zählt Budget, endet bei Notaus |
| OH-05 | R2 | Verbindungen des Workers zu Testlistener/beliebigen Zielen schlagen fehl; einziger Weg ist das Relay |
| OH-06 | R7 | Diff mit `..`, absoluten Pfaden, Reparse Points, Sicherheitsdateien → verworfen/BLOCKED |
| OH-07 | R3 | harter JARVIS-Abbruch: Worker beendet oder beim nächsten Start gemeldet; Aufräumen nur nach Rückfrage |
| OH-08 | R8 | fehlt Docker/WSL/VM → kein Start, keine Ausführung auf dem Host |
| OH-09 | R5 | feindliches Skript (Fork-Bombe, Speicher, Platte, Ausgabeflut, Endlosschleife) wird begrenzt, klarer Grund |
| OH-10 | R6 | Notaus beendet Worker vollständig; `tests/test_*security*.py`, `tests/test_emergency_stop.py` grün |
| OH-11 | R1 | Host-Datei außerhalb der Kopie (Testdatei) ist im Worker nicht sichtbar; Schreibversuch auf Original unmöglich |
| OH-12 | R2/R13 | mitgeschnittener Netzverkehr (Testlistener) zeigt keinen Telemetrie-/Skills-Abruf |
**Nachweisgrenze:** Ob GitHub-Windows-Runner Linux-Container/VMs ausführen können, ist **nicht verifiziert**. Wenn nicht, laufen diese Tests nur manuell am echten PC und sind als „manuell, nicht automatisiert“ zu kennzeichnen. Linux-Ergebnisse sind kein Windows-Nachweis.

## 9. Offene Fragen, Risiken, Blocker
- **Besitzerangaben nötig:** CPU/RAM/freier Speicher; ist Virtualisierung im BIOS aktiv; Nutzung privat oder gewerblich (Docker-Lizenz).
- **Blocker B1:** Docker-Systemanforderungen listen Home nicht; Installierbarkeit/Support auf Home ist offen.
- **Blocker B2:** Q-A bis Q-E (Abschnitt 7) – nur per Prototyp klärbar.
- **Blocker B3:** Telemetrie nicht dokumentiert; Quellcode-Prüfung braucht Download (eigene Freigabe).
- **Risiko:** Container im WSL-2-Kernel sind keine VM-Grenze; WSL-Netzwerk- und Ressourcengrenzen sind global. Der Agent handelt im Worker ohne unsere Einzelprüfung; Sicherheit hängt an Isolation, Bestätigung pro Lauf und Diff-Prüfung.
- **Risiko:** VirtualBox/VMware neben WSL 2 kann Leistung und Stabilität mindern; Lizenzfragen (VirtualBox Extension Pack, VMware-Lizenzseite ungeprüft).
- **Risiko:** `latest`-Tag, Skills-Sync und Image-Pull als Lieferkettenwege.

## 10. Entscheidungen des Besitzers
1. Hardware- und Nutzungsangaben (Abschnitt 9) liefern.
2. Stufenplan bestätigen oder ändern: Container-Prototyp zuerst, VM als Zielvariante bei Bedarf.
3. Docker-Desktop-Lizenz: privat vs. gewerblich klären (mit Docker); oder Engine-Variante O1b prüfen.
4. Freigabe weiterer **reiner Dokumentationsschritte** (Quellcode-Telemetrieprüfung braucht Download und eine eigene Freigabe).
5. Erst danach: Prototyp in Wegwerfumgebung ohne JARVIS-Anbindung (eigene Freigabe, mit Installation). **Jede Übernahme fremden Codes** braucht zuvor Lizenz-, Sicherheits- und Kompatibilitätsprüfung und eine separate Freigabe (Besitzerentscheidung).

## 11. Quellen (gelesen am 2026-11-11)
OpenHands: docs.openhands.dev (`sdk/arch/agent-server`, `openhands/usage/agent-canvas/architecture`, `…/backend-setup/docker-execution`, `sdk/guides/agent-server/docker-sandbox`, `sdk/arch/workspace`, `sdk/arch/security`, `sdk/guides/secrets`, `…/api-reference/git/git-diff`, `sdk/faq`), github.com/OpenHands/OpenHands und /software-agent-sdk (READMEs), openhands.dev/privacy (2025-09-03). PyPI-Seite war nicht lesbar (Challenge).
Docker: docker.com/legal/docker-subscription-service-agreement (2026-08-26), docker.com/pricing/faq, docs.docker.com (`desktop/setup/install/windows-install`, `…/enhanced-container-isolation` und `…/limitations`, `…/settings-management`, `desktop/features/wsl`, `reference/cli/docker/container/run`, `engine/security`, `…/rootless`, `…/seccomp`, `engine/install/ubuntu`).
Microsoft Learn: `windows/wsl/wsl-config` (2026-10-16), `compare-versions`, `faq`, `install-manual`, `networking`, `windows-server/virtualization/hyper-v/overview` und `system-requirements-for-hyper-v-on-windows`, `virtualization/api`.
VM-Anbieter: virtualbox.org (Downloads, Licensing_FAQ, Changelog, Handbuch ch01/04/06/14), qemu.org (download, whpx, net, license), blogs.vmware.com (2024-11-11, 2025-03-10). Nicht abrufbar: Broadcom-Workstation-Seite (404), Multipass-Dokumentation (404).
Intern: `docs/SANDBOX_DESIGN.md`, `docs/INTEGRATIONS.md`, `docs/V2_OPEN_SOURCE_BEWERTUNG.md`, `docs/V2_BACKLOG.md` (V2-15).
