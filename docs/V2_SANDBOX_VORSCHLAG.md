# Sandbox-Entscheidungsvorschlag: isolierter Coding-Worker (OpenHands vorgemerkt)

**Status: Vorschlag zur Besitzerentscheidung. Nichts davon ist umgesetzt, installiert oder freigegeben.** OpenHands ist als bevorzugter Kandidat **vorgemerkt**, ohne Integrations- oder Ausführungsfreigabe. **Coding bleibt vorerst bei der vorhandenen JARVIS-Implementierung** (`coding/`, `self_repair/`, `self_improvement/`). Stand der Recherche: 2026-11-11. Baut auf `docs/SANDBOX_DESIGN.md` (Anforderungen R1–R9, Abnahmetests T1–T13, Optionen A–C) auf und ergänzt sie für diesen Fall. Gehört zu `docs/V2_OPEN_SOURCE_BEWERTUNG.md` (Kandidat 2) und `docs/V2_BACKLOG.md` (V2-15). Release-Freeze für Windows V1 bleibt bestehen; V1-Abnahme #186 steht aus. PermissionEngine, Not-Aus, X0, Audit und Sicherheitsdefaults bleiben unverändert.

## 1. Ausgangslage
**Bestehende Vorgaben** (`docs/SANDBOX_DESIGN.md`): ein fremder Coding-Agent ist nicht vertrauenswürdig; Job-Objekte (`winjob.py`) sind **Eindämmung, keine Isolation**; `ExecutionGuard` bleibt gesperrt; ohne belegte Isolation startet nichts (R8, fail-closed); Start, Dateiübergabe und Rücknahme nur über `ToolRegistry.execute` → `PermissionEngine` mit Bestätigung pro Lauf (R6); Ergebnisse sind Daten und werden nie automatisch übernommen (R7).

**OpenHands, belegt aus den offiziellen Projektseiten** (Quellen in Abschnitt 10):
| Aussage | Beleg |
|---|---|
| Lizenz MIT (OpenHands und `software-agent-sdk`) | LICENSE-Dateien |
| SDK 1.61.0 vom 2026-11-09, `requires_python >=3.12`; App 1.11.0 (2026-07-09) | PyPI |
| Offizieller Windows-Weg: WSL + Docker Desktop (Windows 10/11, WSL 2, „Use the WSL 2 based engine“); die Seite ist die als **veraltet („deprecated legacy local GUI“)** gekennzeichnete Anleitung | Doku Local Setup |
| „Local Runtime“ führt Aktionen **ohne Sandbox** direkt auf dem Rechner aus; unter Windows nur CLI/Headless, Browser-Werkzeug dort nicht unterstützt | Doku Local Runtime / Windows ohne WSL |
| Docker-Sandbox: Agent-Server im Container, „complete isolation from the host system“; Mounts über `SANDBOX_VOLUMES` (`host:container[:mode]`, Standard **read-write**, „Anything mounted read-write into /workspace can be modified by the agent“); optional Host-Netzwerk | Doku Docker-Sandbox |
| Ein LLM-Schlüssel ist für die meisten Modelle nötig; lokale Modelle (LM Studio, llama.cpp, Ollama) möglich | Doku Local Setup |

**Die Dokumentation schweigt zu:** Container-Benutzer, Standard-Mounts, Internetzugang des Containers, CPU-/Speicher-/Prozesslimits, Docker-Socket in der Sandbox, an den Container übergebene Umgebungsvariablen, Aufräumdetails, **Telemetrie**. Das sind keine Befunde „sicher“, sondern **ungeprüft**; jeder dieser Punkte wird zum Test (Abschnitt 7).

## 2. Zusätzliche Anforderungen für OpenHands (Ergänzung zu R1–R9)
| # | Bereich | Anforderung |
|---|---|---|
| R10 | LLM-Zugang | Der Schlüssel bleibt **auf dem Host** und gelangt nie in den Worker (R4). Zugang über ein **host-seitiges LLM-Relay** (nur konfigurierter Endpunkt und Modell, Budget, Protokoll, Notaus) oder über ein lokales Modell. Ohne Relay/lokales Modell hat der Worker keine Netzverbindung und kann nicht arbeiten (fail-closed). |
| R11 | Image-Herkunft | Nur ein per **Digest** gepinntes Image (`name@sha256:…`) aus geprüfter Quelle; kein `latest`, kein Bau und keine Installation zur Laufzeit; Prüfdatei nach `docs/INTEGRATIONS.md` für Image und Basis. |
| R12 | Keine Durchgriffe | Kein Docker-Socket im Worker, kein `--privileged`, kein Host-Netzwerk, kein Host-PID/IPC-Namensraum, keine Geräte. |
| R13 | Telemetrie | Da nicht dokumentiert: Abgang wird durch Netzblockade verhindert und durch Test belegt, nicht angenommen. |

**Grundsätzliche Einordnung:** Innerhalb des Workers handelt der Agent selbständig (Dateien ändern, Befehle ausführen, Tests starten); diese Einzelaktionen laufen **nicht** über unsere `PermissionEngine`. Die Sicherheitsgrenze ist deshalb **die Sandbox selbst plus Bestätigung pro Lauf und Prüfung des Ergebnisses** (R6, R7). Das ist ein bewusster Unterschied zu allen heutigen JARVIS-Werkzeugen und der Grund, warum die Isolation belegt sein muss, bevor irgendetwas startet.

## 3. Optionen für den OpenHands-Worker unter Windows
Beleg der Herstellerangaben: Microsoft Learn (WSL-Konfiguration, Windows Sandbox), Docker-Referenz und -Lizenzvertrag (Abschnitt 10).

| Eigenschaft | O1 Docker Desktop (WSL 2) mit gehärtetem Container | O2 Dedizierte Hyper-V-Linux-VM („jarvis-worker“) | O3 Gehärtete WSL-2-Distribution (ohne Container) | O4 Windows Sandbox | O5 AppContainer |
|---|---|---|---|---|---|
| Von OpenHands offiziell unterstützt | ja (WSL + Docker Desktop) | Linux-Gast: Weg gleich wie Linux; nicht gesondert dokumentiert | Local Runtime ohne Sandbox | nur Windows-CLI/Headless, kein Browser | nein |
| Dateisystem (R1) | Container: `--read-only`, gezielte Mounts; WSL-Laufwerke des Docker-Gastsystems nicht von uns steuerbar (ungeprüft) | VM, **kein** geteilter Ordner; Übergabe per Archiv | `automount.enabled=false` je Distribution (dokumentiert) | ja, Mapped Folder `ReadOnly` | per ACL, Eigenbau |
| Netzwerk (R2) | `--network none` (dokumentiert: nur Loopback); LLM-Weg über Relay ungeklärt (Q2) | privater virtueller Switch ohne Außenadapter, Relay am Host | `networkingMode` ist **global** für alle WSL-2-Distributionen (dokumentiert), nicht je Distribution | `Networking=Disable` (dokumentiert) | Capabilities |
| Zugangsdaten (R4) | Container-Umgebung leer; Relay hält Schlüssel | frische VM, kein Host-SSO | `interop`/`appendWindowsPath` aus (dokumentiert) | frische VM, Zwischenablage aus | eigene Identität |
| Prozesse beenden (R3) | `docker kill`/`rm -f` plus Job Object um die CLI | `Stop-VM`/Checkpoint-Rücksetzen (nicht geprüft) | `wsl --terminate`/`--shutdown` | Fenster/VM schließen verwirft Zustand | Job Object |
| Ressourcen (R5) | `--memory`, `--memory-swap`, `--cpus`, `--pids-limit` (alle in der Referenz) | VM-Speicher/CPU (nicht geprüft) | `.wslconfig` `memory`, `processors`, `swap` **global** | `MemoryInMB` | Job Object |
| Als Sicherheitsgrenze beschrieben | Container teilen den Kernel der WSL-2-VM; keine Herstelleraussage zu „WSL = Grenze“ gelesen | VM-Grenze (laut `SANDBOX_DESIGN.md`/MSRC) | nicht gelesen | VM mit eigenem Kernel | ja (MSRC) |
| Windows-Edition | auch Home (WSL 2) | **Pro/Enterprise** (Hyper-V) | auch Home | **nicht Home** | alle |
| Automatisierbar durch JARVIS | ja (CLI) | ja (PowerShell, Aufwand hoch) | ja | **nicht dokumentiert** (nur Start per `.wsb`-Datei, keine Automatisierung genannt), nur eine Instanz | Eigenbau |
| Zusätzliche Abhängigkeit | **Docker Desktop** (Prüfdatei, Lizenz) | Hyper-V, Linux-Image | – | – | – |
| Aufwand | mittel | hoch | niedrig, aber nicht belastbar | mittel | sehr hoch |
| Bewertung für OpenHands | **geeignet als Fallback** | **geeignet als bevorzugte Variante** | **nein** (R2 nicht je Distribution, Local Runtime ohne Sandbox) | **nein** (kein Linux/Docker, keine Automatisierung, Netz für LLM) | **nein** |

**Docker Desktop, Lizenz (Docker Subscription Service Agreement, Stand 2026-08-26):** kostenlos nur für nichtkommerzielle Open-Source-Projekte oder Unternehmen mit weniger als 250 Beschäftigten **und** weniger als 10 Mio. US-$ Jahresumsatz; Behörden brauchen immer ein Abonnement. Ob **rein persönliche, nichtkommerzielle** Nutzung ohne Open-Source-Bezug frei ist, sagt der Text **nicht eindeutig**. Das muss der Besitzer mit Docker klären, bevor O1 weiterverfolgt wird.

## 4. Konkreter Vorschlag
**Vorschlag A (bevorzugt, falls Windows Pro/Enterprise/Education): O2 dedizierte Hyper-V-Linux-VM**, darin der OpenHands-Agent-Server (bei Bedarf zusätzlich als gehärteter Container, also zwei Grenzen).
- Begründung: stärkste belegbare Grenze (eigener Kernel, privater Switch), keine Docker-Desktop-Abhängigkeit oder -Lizenzfrage, Zustand per Checkpoint rücksetzbar, deckt sich mit der Empfehlung des bestehenden Entwurfs („C oder B für den ersten Prototyp“).
- Nachteil: Aufwand (Image, Aktualisierung, Steuerung per PowerShell, Dateiübergabe); nicht auf Windows Home.

**Vorschlag B (Fallback, auch Windows Home): O1 Docker Desktop mit WSL 2 und gehärtetem Container.**
- Voraussetzungen vor jedem Prototyp: Lizenzklärung (oben), Prüfdatei `docs/integrations/docker-desktop.md`, Härtung und Nachweis durch T1–T13 und die Zusatztests OH-01 bis OH-10.
- Nachteil: Container teilen den Kernel der WSL-2-VM; Docker-Engine-Steuerung ist ein mächtiges Werkzeug (nur feste Befehlsvorlagen, nie vom Agenten gewählte Argumente).

**Nicht empfohlen:** O3 (WSL ohne Container), O4 (Windows Sandbox), O5 (AppContainer) für diesen Zweck (Begründung in der Tabelle).

**Entscheidungsbaum:** Windows-Edition Pro oder höher? → Vorschlag A. Home, oder A zu aufwendig? → Lizenz klären → Vorschlag B. Keins davon gewünscht → Coding bleibt bei der vorhandenen Implementierung (Option A der Open-Source-Bewertung); das ist ausdrücklich eine zulässige Entscheidung.

## 5. Isolationsspezifikation (für A und B)
Jede Einstellung ist als **dokumentiert** (Herstellerseite gelesen) oder **ungeprüft** markiert; ungeprüfte Punkte werden vor einem Prototyp geklärt.

**Dateisystem (R1, R7).** Der Worker erhält eine **schreibgeschützte Kopie** des Arbeitsstands (Export ohne `.git`, ohne Geheimnisse) und ein **leeres** Arbeits-/Ausgabeverzeichnis; nichts anderes vom Host. Rückgabe nur als Diff plus Dateiliste, durch `PathGuard` und Bestätigung, nie automatisch angewendet.
- Container: `--read-only` (dokumentiert: Wurzel schreibgeschützt), `--tmpfs /tmp:rw,noexec,nosuid,size=…` (dokumentiert), `--user <UID>:<GID>` (dokumentiert, kein Root), Bind-Mount der Kopie nur lesend (Syntax `--mount … readonly` bzw. `-v …:ro` im gelesenen Referenztext **nicht wörtlich bestätigt**), kein Docker-Socket, kein `--privileged` (die Referenz warnt ausdrücklich: „A container with `--privileged` is not a securely sandboxed process“).
- WSL: `[automount] enabled=false`, `[interop] enabled=false`, `appendWindowsPath=false` (dokumentiert, je Distribution; ob sie sich für das von Docker Desktop verwaltete System ändern lassen, ist **ungeprüft**).
- VM: kein geteilter Ordner; Übergabe als Archiv (Mechanismus **ungeprüft**, im Prototyp zu klären).

**Netzwerk (R2, R10, R13).** Standard: keins. Container: `--network none` (dokumentiert: nur Loopback). Für den LLM-Zugang ist ein **host-seitiges Relay** vorgesehen (Endpunkt-/Modell-Allowlist, Budget, Protokoll, Notaus, hält den Schlüssel); wie der Worker **ausschließlich** das Relay erreicht (z. B. internes Netz, ein einziger erlaubter Weg), ist **offen** (Q2). Alternative ohne Relay: lokales Modell auf dem Host mit ebenfalls nur diesem Weg. Windows-Firewall-/Hyper-V-Firewall-Regeln (WSL: `[wsl2] firewall=true` filtert laut Doku den WSL-Verkehr) sind eine zusätzliche, **keine alleinige** Schicht.

**Prozessbeendigung (R3, R6).** Alle Host-seitigen Steuerprozesse (`docker`-CLI bzw. PowerShell) laufen als Kindprozesse unter einem **Job Object** (`self_improvement/winjob.py`, über `bootstrap.py` eingebunden). Notaus und Abbruch: (1) Job beenden, (2) Container/VM **namentlich** (Präfix `jarvis-worker-<Lauf-ID>`, Label) hart stoppen und entfernen (`docker kill`/`rm -f` bzw. `Stop-VM`), (3) Gegenprobe, dass nichts Gelabeltes mehr läuft; ist die Gegenprobe nicht sauber, meldet JARVIS **unvollständigen Abbruch** (wie im Entwurf gefordert). Container mit `--rm`, `--init` und `--stop-timeout` (alle in der Referenz). Nach hartem JARVIS-Ende: beim nächsten Start nur **lesende** Suche nach verwaisten Workern und Rückfrage vor dem Aufräumen.

**Ressourcen (R5).** Container: `--memory` und `--memory-swap` gleich (dokumentiert: dann **kein** Swap), `--cpus`, `--pids-limit`, `--ulimit`, tmpfs-Größe; Wanduhrzeit, Ausgabemenge und Gesamtbudget zusätzlich auf JARVIS-Seite. WSL: `memory`, `processors`, `swap` in `.wslconfig` sind **global** für alle WSL-2-Distributionen (dokumentiert) und verändern die übrige WSL-Nutzung. Plattenquota je Container und Hyper-V-Limits: **ungeprüft**. Richtwerte für einen Prototyp (zu messen, nicht zu glauben): 4 GB RAM, 2 CPUs, 256 Prozesse, 10 Minuten je Lauf.

**Audit (R6, R9).** Je Lauf ein geschwärzter Eintrag: Lauf-ID, Image-Digest, Hash der tatsächlich wirksamen Isolationskonfiguration (Grundlage der `IsolationAttestation`), Auftragshash, Relay-Statistik (Aufrufe, Tokens, Modell), Dauer, Ressourcenspitzen, Abbruchgrund, Hash des Ergebnis-Diffs, Entscheidung der Übernahme. **Grenze:** Einzelaktionen des Agenten im Worker sind nicht einzeln auditierbar; nur Container-/VM-Log und Ergebnis.

## 6. Ablauf eines Laufs (Sollbild, nicht implementiert)
1. Nutzer beauftragt einen Coding-Lauf; Assistent plant; `ToolRegistry.execute` → `PermissionEngine` mit **Bestätigung pro Lauf** (Auftrag, Quelle, Image-Digest, Limits sichtbar).
2. Vorprüfung fail-closed: Isolationsfunktion vorhanden, Attestation aktuell (Tests im selben Stand grün), Image-Digest passt, Relay bereit; sonst **kein Start**.
3. Export der schreibgeschützten Kopie, Anlegen des leeren Ausgabeverzeichnisses.
4. Start des Workers mit festen Befehlsvorlagen unter Job Object; nur Relay-Netz.
5. Agent arbeitet im Worker innerhalb der Limits.
6. Ende, Zeitlimit, Abbruch oder Notaus → harter Stopp und Entfernen (Abschnitt 5).
7. Ergebnis (Diff) wird als **nicht vertrauenswürdige Daten** zurückgegeben: `PathGuard`, Anzeige im Freigabedialog.
8. Übernahme **nur nach Bestätigung**; kein automatisches Anwenden, kein Commit, kein Push.
9. Audit-Eintrag; Worker und Ausgabeverzeichnis aufgeräumt.

## 7. Abnahmetests
Alle Tests aus `docs/SANDBOX_DESIGN.md` (T1–T13) gelten unverändert. Zusätzlich:

| ID | Prüft | Bestanden, wenn |
|---|---|---|
| OH-01 | R11 | abweichender oder fehlender Image-Digest → Start verweigert; kein `latest`; kein Bau/Pull zur Laufzeit |
| OH-02 | R12 | kein Docker-Socket, kein `--privileged`, kein Host-Netz/PID im tatsächlich wirksamen Start (Konfiguration wird gelesen, nicht angenommen) |
| OH-03 | R4/R10 | Umgebung und Dateisystem des Workers enthalten keinen Schlüssel, kein SSO-Token; Suche nach Testschlüssel negativ |
| OH-04 | R10 | Relay erlaubt nur konfigurierten Endpunkt/Modell, zählt Budget, bricht bei Überschreitung ab, endet bei Notaus |
| OH-05 | R2/R13 | Verbindungsversuche des Workers zu einem lokalen Testlistener und zu beliebigen Zielen schlagen fehl; einziger Weg ist das Relay |
| OH-06 | R7 | Diff mit `..`, absoluten Pfaden, Reparse Points, Änderungen an Sicherheitsgrenzen → verworfen bzw. BLOCKED |
| OH-07 | R3 | harter Abbruch von JARVIS: Worker ist danach nicht mehr aktiv oder wird beim nächsten Start gemeldet; Aufräumen nur nach Rückfrage |
| OH-08 | R8 | fehlt Docker/VM/Funktion → kein Start, keine Ausweichausführung auf dem Host |
| OH-09 | R5 | feindliches Testskript (Fork-Bombe, Speicher, Platte, Ausgabeflut, Endlosschleife) wird vom Limit beendet mit klarem Grund |
| OH-10 | R6 | Notaus beendet laufenden Worker vollständig; Bericht benennt Unvollständigkeit; `tests/test_*security*.py`, `tests/test_emergency_stop.py` bleiben grün |

**Nachweisgrenze:** Ob die GitHub-Windows-Runner Linux-Container oder Hyper-V ausführen können, ist **nicht verifiziert**. Falls nicht, sind diese Tests nicht in der CI belegbar und müssen am echten PC laufen. Dann sind sie **klar als „manuell, nicht automatisiert“ zu kennzeichnen** und ersetzen nie die CI-Belege der übrigen Tests.

## 8. Risiken, offene Fragen, Blocker
- **Q1** Wo läuft die LLM-Schleife des SDK (im Worker oder im Aufrufer)? Davon hängt ab, ob der Worker mit `--network none` arbeiten kann. In der gelesenen Doku nicht beantwortet.
- **Q2** Wie erreicht der Worker ausschließlich das Relay (internes Netz, ein Weg)?
- **Q3** Was sendet OpenHands standardmäßig nach außen (Telemetrie, Paketabrufe)? Nicht dokumentiert.
- **Q4** Dateiübergabe in eine VM ohne geteilten Ordner; Container-Benutzer und Standard-Mounts des offiziellen Images.
- **Q5** Docker-Desktop-Lizenz für private Nutzung; Windows-Edition des Besitzers.
- **Q6** Ressourcenbedarf (RAM/CPU/Platte) und Laufzeit in der Praxis.
- **B1** Netzwerkisolation eines Kindprozesses unter Windows ohne Sandbox bleibt ungelöst (Entwurf `SANDBOX_DESIGN.md`).
- **B2** CI-Belegbarkeit der Sandbox-Tests (Abschnitt 7).
- **Risiko:** Ein Agent mit eigener Schleife und Werkzeugen im Worker ist nur so sicher wie die Grenze; deshalb **kein** Start ohne gültige Attestation und ohne Bestätigung pro Lauf.

## 9. Entscheidungen des Besitzers
1. Windows-Edition (Home/Pro/…): bestimmt Vorschlag A oder B.
2. Vorschlag A, Vorschlag B oder Coding bei der vorhandenen Implementierung belassen?
3. Bei B: Docker-Desktop-Lizenz klären und Prüfdatei `docs/integrations/docker-desktop.md` freigeben?
4. Soll als nächster reiner Dokumentationsschritt die Klärung von Q1 bis Q4 anhand der Projektdokumentation erfolgen (ohne Installation)?
5. Erst danach: Prototyp in einer Wegwerfumgebung ohne JARVIS-Anbindung (eigene Freigabe, mit Installation).

## 10. Quellen
OpenHands: [Local Setup (veraltete GUI-Anleitung)](https://docs.openhands.dev/openhands/usage/run-openhands/local-setup) · [Docker-Sandbox](https://docs.openhands.dev/openhands/usage/sandboxes/docker.md) · [SDK DockerWorkspace](https://docs.openhands.dev/sdk/guides/agent-server/docker-sandbox.md) · LICENSE von [OpenHands](https://github.com/OpenHands/OpenHands) und [software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) · PyPI `openhands-sdk`, `openhands-ai`.
Windows und Docker: [WSL-Konfiguration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) (Stand der Seite 2026-10-16) · [Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview) · [.wsb-Konfiguration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file) · [Docker: Ressourcenlimits](https://docs.docker.com/engine/containers/resource_constraints/) · [Docker: Netzwerk none](https://docs.docker.com/engine/network/drivers/none/) · [docker run](https://docs.docker.com/reference/cli/docker/container/run/) (Teile der Seite nur als Zusammenfassung gelesen) · [Docker Subscription Service Agreement](https://www.docker.com/legal/docker-subscription-service-agreement/).
Alles Weitere: siehe `docs/SANDBOX_DESIGN.md` Abschnitt 8.
