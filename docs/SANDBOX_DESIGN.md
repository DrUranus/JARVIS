# Entwurf: OS-Sandbox fuer das Ausfuehren fremder Coding-Agenten (`os-sandbox-design`)

**Status: reiner Entwurf. Kein Code, nichts implementiert, nichts aktiviert.** Dieses Dokument legt fest, was unter Windows belastbar isolieren kann, was nicht, und welche Anforderungen und Abnahmetests eine Sandbox erfuellen muss, bevor ein externer Coding-Agent (z. B. ein CLI-Agent eines Drittanbieters) eingebunden werden darf.

**Entscheidung des Besitzers erforderlich.** Dieser Entwurf trifft keine Wahl zwischen den Optionen und gibt nichts frei. Bis der Besitzer eine Option ausdruecklich freigibt (eigener Backlog-Schritt mit `approved: true`) und deren Abnahmetests (Abschnitt 7) in der Windows-CI gruen sind, gilt:

> **Externe Coding-Agenten werden nicht eingebunden, nicht gestartet und nicht konfigurierbar gemacht.** `ExecutionGuard` bleibt gesperrt (`src/jarvis/self_improvement/isolation.py`), `allow_prepare`/`allow_activation`/`repo_path` werden weiter abgelehnt.

## 1. Begriffe: Eindaemmung vs. Isolation

| Begriff | Bedeutung hier | Beispiel |
|---|---|---|
| **Eindaemmung (containment)** | Begrenzt Ressourcen und Lebensdauer eines Prozessbaums, haelt Fehler klein. Ein feindlicher Prozess mit den Rechten des Benutzers kann trotzdem Dateien lesen/schreiben, das Netzwerk nutzen und Zugangsdaten abgreifen. | Job-Objekt mit `KILL_ON_JOB_CLOSE`, `taskkill /T` |
| **Isolation** | Eine vom Betriebssystem erzwungene Grenze: Der Prozess hat nach der Konfiguration *nicht mehr die Rechte des Benutzers*. Zugriff auf Dateien, Netzwerk, Zugangsdaten und andere Prozesse ist standardmaessig verweigert und nur gezielt gewaehrt. | AppContainer, Hypervisor-VM |
| **Belastbar** | Hier: Der Hersteller beschreibt den Mechanismus als Sicherheitsgrenze **und** unsere eigenen Tests (Abschnitt 7) belegen jede geforderte Eigenschaft auf dem Zielsystem. Eine Herstelleraussage allein genuegt nicht. | |

Ein Linux-Lauf ist kein Windows-Nachweis (Windows-Nachweis liefert nur der CI-Windows-Lauf, `.github/workflows/tests.yml`).

## 2. Bedrohungsmodell

Ein fremder Coding-Agent ist **nicht vertrauenswuerdig**: Er liest Repository-Inhalte (Prompt-Injection), erzeugt und fuehrt Code aus, installiert Pakete und startet Kindprozesse. Angenommen wird ein Agent, der durch Fehlverhalten oder Manipulation absichtlich boesartig handelt, aber nur die Rechte eines normalen (nicht administrativen) Windows-Benutzers hat und keinen Kernel-Exploit besitzt. Nicht abgedeckt: Kernel-/Hypervisor-Schwachstellen, Seitenkanaele, Hardwareangriffe, ein Agent mit Administratorrechten (Administratoren gehoeren zur Trusted Computing Base, siehe [MSRC-Kriterien](#8-quellen)).

## 3. Anforderungen an jede Sandbox

Jede Anforderung ist mit einem Abnahmetest in Abschnitt 7 verknuepft. Fehlt eine, ist die Sandbox nicht belastbar.

| # | Bereich | Anforderung |
|---|---|---|
| R1 | Dateisystem | Lesezugriff nur auf eine **schreibgeschuetzte Kopie** des Arbeitsstands (Export ohne `.git`); Schreibzugriff nur auf ein leeres, eigens angelegtes Ausgabeverzeichnis. Kein Zugriff auf Home-Verzeichnis, `%APPDATA%`, `%USERPROFILE%\.ssh`, Browserprofile, JARVIS-Konfiguration, Schluesseldatei (HMAC), Audit-Log, das Haupt-Repository und dessen `.git/hooks`. Kein Folgen von Junctions/Symlinks aus dem Arbeitsbereich heraus. |
| R2 | Netzwerk | Standard: **kein** Netzwerk (kein Loopback zu JARVIS-Diensten, kein LAN, kein Internet, kein DNS). Eine Ausnahme (z. B. nur der LLM-Endpunkt des Agenten) braucht eine eigene ausdrueckliche Freigabe, Allowlist pro Ziel und Protokollierung. Daten duerfen nie ohne Freigabe in die Cloud gehen (siehe `docs/LLM_ROUTING.md`). |
| R3 | Prozesse | Alle Kindprozesse (auch abgekoppelte) werden zuverlaessig beendet, auch wenn JARVIS selbst abstuerzt. Keine Sicht auf/Einwirkung auf Prozesse ausserhalb der Sandbox (kein Handle auf JARVIS, kein `OpenProcess`, kein Fensternachrichten-Versand an Desktop-Fenster, keine Eingabeinjektion). Begrenzte Prozessanzahl. |
| R4 | Zugangsdaten | Keine Umgebungsvariablen, Tokens, API-Schluessel, gespeicherten Windows-Anmeldeinformationen (Credential Manager), Browser-/SSH-/Git-Credentials, kein geerbter Authentifizierungskontext (Kerberos/NTLM-Single-Sign-On), keine Zwischenablage des Hosts. Der Agent erhaelt nur, was der Auftrag ausdruecklich vorsieht; ein Schluessel fuer den Agenten wird nie in Logs/Commits geschrieben. |
| R5 | Ressourcen | Begrenzte CPU-Zeit, Wanduhrzeit, Arbeitsspeicher, Plattenplatz im Ausgabeverzeichnis, Ausgabemenge (stdout/stderr) und Prozessanzahl; Ueberschreitung beendet den Lauf und wird als solcher gemeldet. |
| R6 | Kontrollpfad | Start, Dateiuebergabe und Ergebnisruecknahme nur ueber `ToolRegistry.execute` -> `PermissionEngine` (Bestaetigung pro Lauf); Verdrahtung nur in `src/jarvis/bootstrap.py`; Notaus (`docs/PHASE14_AUTONOMY.md`) beendet die Sandbox vollstaendig und meldet unvollstaendigen Abbruch. |
| R7 | Ergebnisrueckgabe | Ergebnisse (Diff/Dateien) gelten als **nicht vertrauenswuerdige Daten**: Pruefung durch Pfadregeln (`PathGuard`) und Bestaetigung vor jeder Uebernahme; kein automatisches Anwenden, kein Commit/Push, keine Selbstmodifikation. |
| R8 | Fail-closed | Fehlt Sandbox-Funktion (Edition, Virtualisierung, Berechtigung, Zuweisungsfehler), startet der Agent **nicht**; es gibt keinen Rueckfall auf ungeschuetzte Ausfuehrung. |
| R9 | Nachweis | Jede Eigenschaft ist durch einen Test belegt, der **auf Windows** laeuft (CI); die Sandbox legt eine `IsolationAttestation` (`isolation.py`) nur vor, wenn diese Tests im selben Stand bestanden haben. |

## 4. Optionen unter Windows

Bewertung: **Was bietet die Option? Was bietet sie ausdruecklich nicht?** Quellen in Abschnitt 8.

### 4.1 Job-Objekte (bereits im Einsatz: `winjob.py`)

- **Bietet:** Verwaltung einer Prozessgruppe als Einheit; Limits (Arbeitssatz, Prioritaet, Prozessanzahl, CPU-Zeit, Job-/Prozessspeicher, CPU-Rate); `TerminateJobObject`; `KILL_ON_JOB_CLOSE` beendet alle Prozesse beim Schliessen des letzten Handles; Buchfuehrung; UI-Einschraenkungen (`JOBOBJECT_BASIC_UI_RESTRICTIONS`, z. B. Clipboard, Desktop-Wechsel, Handles auf Fenster ausserhalb des Jobs).
- **Bietet nicht:** Dateisystem-, Registry-, Netzwerk- oder Berechtigungsbeschraenkung. Die Dokumentation beschreibt Job-Objekte als Mittel, "groups of processes to be managed as a unit"; sie sind dort nicht als Sicherheitsgrenze beschrieben, und die MSRC-Seite fuehrt sie nicht als Grenze. Sicherheitslimits muessen "individually for each process" gesetzt werden. Breakaway (`CREATE_BREAKAWAY_FROM_JOB`) ist nur ausgeschlossen, wenn `BREAKAWAY_OK`/`SILENT_BREAKAWAY_OK` nicht gesetzt sind. Kinder, die per `Win32_Process.Create` (WMI) gestartet werden, gehoeren laut Dokumentation nicht zum Job.
- **Rolle im Entwurf:** notwendiger Baustein fuer R3 und R5 (Prozessbaum beenden, Limits), **niemals allein ausreichend**.

### 4.2 Eingeschraenkte Tokens (`CreateRestrictedToken`)

- **Bietet:** Entfernen von Privilegien, "deny-only"-SIDs, Liste von *restricting SIDs* (zweite Zugriffspruefung). Gewoehnliche Anwendungen koennen ihr eigenes Token einschraenken und damit `CreateProcessAsUser` ohne `SE_ASSIGNPRIMARYTOKEN_NAME` nutzen.
- **Bietet nicht:** keine Netzwerkisolation, kein Schutz von Objekten, deren DACL die restricting SIDs (z. B. `Everyone`, `Users`) zulaesst; die Wirkung haengt von den ACLs aller Zielobjekte ab. Die Dokumentation verlangt zusaetzlich einen **anderen Desktop**, um Angriffe per `SendMessage`/`PostMessage` auf Fenster des Standarddesktops zu verhindern. Als eigenstaendige Sicherheitsgrenze wird es dort nicht beschrieben.
- **Rolle:** Eindaemmung/Haertung als Zusatzschicht; allein nicht belastbar fuer R1/R2/R4.

### 4.3 AppContainer

- **Bietet (laut Dokumentation):** Credential-, Device-, Datei-, Netzwerk-, Prozess- und Fensterisolation; Zugriff nur auf gezielt gewaehrte Ressourcen (Dateien/Registry-Schluessel, Netzwerkfaehigkeiten wie Internet/Intranet/Server getrennt); eigenes Identitaetskonzept pro Benutzer/App. MSRC fuehrt die "AppContainer sandbox boundary" als **Sicherheitsgrenze**, die der Hersteller wartet.
- **Bietet nicht / Aufwand:** Es gibt keinen fertigen "starte dieses Programm im AppContainer"-Befehl fuer Benutzer; ein AppContainer-Profil, ACLs auf den freigegebenen Ordnern fuer die AppContainer-SID und ein Start per `CreateProcess` mit Security-Capabilities-Attribut sind Eigenbau (ctypes/Win32). Programme, die nicht fuer AppContainer ausgelegt sind (Interpreter, Paketmanager, Node/Python-Toolchains, CLI-Agenten), scheitern haeufig an Zugriffen auf Standardpfade; Kompatibilitaet ist **unbelegt** und muss pro Agent getestet werden. Netzwerk wird ueber *Capabilities* gesteuert; fehlt `internetClient`, ist ausgehender Verkehr gesperrt. Loopback-Verkehr zwischen AppContainer und Desktop-Prozessen ist standardmaessig gesperrt (Ausnahmen existieren und muessten als nicht gesetzt belegt werden).
- **Rolle:** stärkste *prozess-lokale* Option ohne Virtualisierung; Kandidat A (Abschnitt 5).

### 4.4 Windows Sandbox

- **Bietet:** eine wegwerfbare, hypervisorbasierte Windows-VM ("separate kernel"), startet bei jedem Mal sauber, Zustand wird beim Schliessen verworfen. Konfiguration per `.wsb`-Datei: Netzwerk **aus** moeglich, Mapped Folders mit `ReadOnly`, `LogonCommand`, Speicher (`MemoryInMB`), Zwischenablage/Audio/Video/Drucker abschaltbar, `ProtectedClient` (zusaetzlich AppContainer-Isolation des Clients).
- **Bietet nicht / Grenzen:** Standardwerte sind **unsicher fuer unseren Zweck**: Netzwerk an, Zwischenablage an, Audio-Eingang an, vGPU an (vergroessert laut Doku die Angriffsflaeche); Mapped Folders sind standardmaessig beschreibbar und "can be compromised by apps in the sandbox". Der Benutzer in der VM soll Administrator sein (`WDAGUtilityAccount`). Nur Windows Pro/Enterprise/Education, **nicht Home**; benoetigt Virtualisierung; "currently doesn't allow multiple instances to run simultaneously". Die Doku nennt keine feinen CPU-/Plattenlimits ausser Speicher; eine programmgesteuerte, strukturierte Schnittstelle (Exit-Code, Ausgabe, Zeitlimit von aussen) ist nicht Teil der dokumentierten Konfiguration; Ergebnisrueckgabe liefe ueber einen beschreibbaren Mapped Folder, was R1/R7 beruehrt. Das Beenden von aussen und das Erzwingen von Zeitlimits muss ein Wrapper leisten (unbelegt). Windows Sandbox wird bei MSRC nicht gesondert als Grenze aufgefuehrt (nicht klassifiziert); der Hypervisor-Mechanismus entspricht aber der VM-Grenze.
- **Rolle:** starke Isolation fuer gelegentliche, bestaetigte Laeufe auf Pro-Rechnern; Kandidat B.

### 4.5 WSL 2 / Hyper-V-VM

- **WSL 2:** laeuft in einer leichtgewichtigen Hyper-V-VM; Distributionen sind Container innerhalb **einer gemeinsamen VM** und teilen Netzwerk-Namespace, Kernel, CPU/Speicher. Standardmaessig sind Windows-Laufwerke unter `/mnt/c` gemountet (`automount.enabled = true`), Windows-Programme sind startbar (`interop.enabled = true`) und `appendWindowsPath = true`; `localhostForwarding` und NAT-Netzwerk sind an. Abschaltbar: `automount.enabled=false`, `interop.enabled=false`, `appendWindowsPath=false`, `networkingMode=none`, Limits `memory`/`processors`/`swap`/`defaultVhdSize`. Die Dokumentation beschreibt WSL als Entwicklungsumgebung ("seamless"), **nicht** als Sandbox; unter `\\wsl$`/`\\wsl.localhost` ist das Linux-Dateisystem vom Windows-Benutzer aus erreichbar. Mit allen Windows-Bruecken abgeschaltet nahert sich WSL 2 einer VM-Isolation, aber diese Haertung ist ein Konfigurationsstand pro Benutzer (`.wslconfig` im Benutzerprofil, `wsl.conf` im Gastsystem), den der Agent selbst nicht aendern duerfen soll; ein Agent im selben WSL-Benutzer koennte ihn aber potenziell umstellen (unbelegt, muss durch Test widerlegt werden).
- **Hyper-V-VM (eigene, dedizierte Gast-VM):** MSRC fuehrt die **Virtual-Machine-Boundary** als Sicherheitsgrenze. Voraussetzung: Hyper-V (Pro/Enterprise), Gast-Installation, Verwaltung von Snapshots/Netzwerk/Freigaben durch uns. Aufwand und Wartung hoch.
- **Rolle:** WSL 2 nur mit strikter Haertung und Nachweis; dedizierte VM ist die robusteste, aber aufwendigste Option (Kandidat C). Linux-Agenten (die Mehrzahl der CLI-Agenten) laufen dort nativ.

### 4.6 Nicht empfohlen / ausgeschlossen

- **Windows-Server-Container** (Process-Isolation): laut MSRC "not intended to be used in hostile multitenancy scenarios".
- **Nur anderer Benutzerkonto-Start** (`runas`/Dienstkonto): Eindaemmung nach Benutzerrechten, aber Einrichtung erfordert Administrator, lokale Zugangsdaten des zweiten Kontos und ACL-Pflege; unbelegte Netzwerk-/Prozessisolation. Nur als Zusatz.
- **Reine Pfad-/Textfilter, `PathGuard`, AST-Pruefung, bereinigte Umgebungsvariablen:** Filter, keine Isolation (siehe `README.md` zu `ToolGateway`).
- **Docker Desktop:** nicht Teil dieses Entwurfs; haengt von WSL 2/Hyper-V ab und ist zusaetzliche Abhaengigkeit (Pruefschema `docs/INTEGRATIONS.md` waere noetig).

## 5. Vergleich

| Eigenschaft | Job-Objekt | Restricted Token | AppContainer | Windows Sandbox | WSL 2 (gehaertet) | Eigene Hyper-V-VM |
|---|---|---|---|---|---|---|
| Dateisystem (R1) | nein | teilweise (ACL-abhaengig) | ja, per ACL/Capabilities | ja (VM, nur Mapped Folders) | nur mit `automount=false` und Pruefung | ja (VM) |
| Netzwerk (R2) | nein | nein | ja (Capabilities), Loopback pruefen | ja, `Networking=Disable` | `networkingMode=none` | ja (virtueller Switch) |
| Zugangsdaten (R4) | nein | teilweise | ja (eigene Identitaet) | ja (frische VM), Clipboard aus | ja, wenn `interop` aus | ja |
| Prozesse (R3) | Beenden ja, Isolation nein | nein | ja (Kernelobjekte) | ja (VM) | ja (VM), aber gemeinsame VM | ja |
| Ressourcen (R5) | ja | nein | nur mit Job-Objekt | nur Speicher dokumentiert | `memory`/`processors`/`swap`/`defaultVhdSize` | ja |
| Als Grenze beim Hersteller | nein | nein | ja (MSRC) | VM-Hypervisor, nicht gesondert gelistet | nicht als Sandbox beschrieben | ja (VM-Grenze) |
| Windows Home | ja | ja | ja | **nein** | ja (Funktion), Hyper-V-Details unbelegt | **nein** |
| Aufwand | gering (vorhanden) | mittel | hoch (Eigenbau, Kompatibilitaet) | mittel (Wrapper noetig) | mittel | hoch |
| Reicht allein | nein | nein | ja, falls Tests bestehen | ja, falls Tests bestehen | nur mit Nachweis | ja, falls Tests bestehen |

## 6. Bezug zu `winjob.py` und `winsec.py`

- **`src/jarvis/self_improvement/winjob.py`** ist **Eindaemmung, keine Isolation**. Es erzeugt ein Job-Objekt mit `KILL_ON_JOB_CLOSE`, weist den suspendiert gestarteten Prozess zu und gibt ihn dann frei. Es setzt keine Datei-, Netzwerk- oder Rechtegrenzen. Eigene Doku-Grenzen im Modul: ein Prozess, der vor der Zuweisung stirbt/JARVIS-Absturz im Zeitfenster, Zuweisungsfehler (z. B. verschachtelter Job ohne Breakaway) fuehren zu Rueckfall auf `taskkill /T`, was fuer verwaiste Enkel **keine** Garantie ist. Fuer eine Sandbox waere `winjob` hoechstens ein *Teilbaustein* (R3/R5), und nur wenn fuer die Sandbox ein Rueckfall verboten ist (R8: bei Zuweisungsfehler nicht starten).
- **`src/jarvis/self_improvement/winsec.py`** prueft und setzt die ACL der HMAC-Schluesseldatei (SDDL-Analyse, `icacls`). Das ist **Dateischutz fuer einen Schluessel des eigenen Benutzers**, keine Prozess- oder Agenten-Isolation. Fuer die Sandbox ist die Pruefmethodik (effektive DACL, fremde Prinzipale ablehnen) wiederverwendbar, etwa um zu belegen, dass die AppContainer-SID oder ein Sandbox-Benutzer keinen Zugriff auf Schluessel, Audit-Log oder Konfiguration hat (Tests T1, T4).
- **`isolation.py`** definiert bereits die geforderten Eigenschaften (`REQUIRED_PROPERTIES`) und die `IsolationAttestation`. Dieser Entwurf bildet sie auf R1-R9 ab: `unprivileged_user` -> R1/R4, `no_host_credentials` -> R4, `no_network` -> R2, `no_main_repository` -> R1, `resource_limits` -> R5, `kills_all_descendants` -> R3, `platform_tests_passed` -> R9. Es existiert kein Backend; dieses Dokument aendert das nicht.

## 7. Abnahmetests (muessen vor jeder Freigabe bestehen)

Alle Tests laufen **auf Windows in der CI** (`tests-windows`), ohne Netzwerkzugriff nach aussen (Netzwerk-Tests pruefen *Blockade* gegen einen lokalen Testserver, nie gegen das Internet), ohne echte API-Schluessel und mit einem harmlosen Test-Agenten (kleines Skript, das gezielt verbotene Dinge versucht). Ein uebersprungener Test gilt nie als bestanden. Linux-Laeufe gelten hoechstens fuer plattformneutrale Logik (Wrapper, Konfigurationspruefung) und sind kein Nachweis.

| Test | Prueft | Bestanden, wenn |
|---|---|---|
| T1 Dateien lesen | R1 | Testagent kann Home, `%APPDATA%`, Schluesseldatei, Audit-Log, Haupt-Repository, `.git/hooks` nicht lesen (Zugriff verweigert); Zugriff ueber Junction/Symlink/8.3-Namen/`\\?\`/UNC/Alternate Data Stream schlaegt ebenfalls fehl |
| T2 Dateien schreiben | R1 | Schreiben in die Kopie des Arbeitsstands scheitert; Schreiben ausserhalb des Ausgabeverzeichnisses scheitert; Schreiben im Ausgabeverzeichnis ist erlaubt und begrenzt |
| T3 Kein Repository | R1 | Der Export enthaelt kein `.git`; Verbindung zum Haupt-Repository nicht moeglich |
| T4 Zugangsdaten | R4 | Weder Umgebungsvariablen mit Schluesselnamen noch Credential Manager, `.ssh`, Browserprofile, Git-Credentials, Zwischenablage noch SSO-Token sind erreichbar |
| T5 Netzwerk | R2 | Ausgehende TCP/UDP-Verbindungen (inkl. DNS, Loopback und LAN-Adresse) zu einem lokalen Testlistener scheitern; Ausnahmeliste ist leer, solange keine Freigabe besteht |
| T6 Prozesse | R3 | Kein Zugriff auf Prozesse/Fenster ausserhalb (`OpenProcess` auf Testprozess scheitert; `SendMessage`/`SetWindowsHookEx`/Eingabeinjektion scheitert); Prozessanzahl begrenzt |
| T7 Kinder beenden | R3 | Detachte Enkelprozesse, `Win32_Process.Create`-Starts und Breakaway-Versuche ueberleben weder Zeitlimit noch Abbruch noch JARVIS-Absturz (Elternprozess hart beendet) |
| T8 Ressourcen | R5 | Speicher-, CPU-, Zeit-, Platten-, Ausgabe- und Prozesslimits greifen, der Lauf endet mit klarem Grund |
| T9 Fail-closed | R8 | Fehlende Funktion (Edition, Virtualisierung, Zuweisungsfehler) fuehrt zu "kein Start", nie zu ungeschuetzter Ausfuehrung |
| T10 Kontrollpfad | R6 | Start nur ueber `ToolRegistry.execute` -> `PermissionEngine` mit Bestaetigung; Notaus beendet die Sandbox, Bericht nennt unvollstaendigen Abbruch; bestehende Sicherheitsregression (`tests/test_*security*.py`, `tests/test_emergency_stop.py`) bleibt gruen |
| T11 Ergebnisrueckgabe | R7 | Rueckgabe geht nur durch `PathGuard` und Bestaetigung; Pfade ausserhalb (`..`, absolute, Reparse Points) werden verworfen |
| T12 Haertungsstand | R9 | Der Test liest die *tatsaechlich wirksame* Konfiguration (z. B. `.wsb`-Optionen, `wsl.conf`, AppContainer-Capabilities) und schlaegt bei jeder Abweichung vom Sollstand rot an |
| T13 Plattform | R9 | Alle Tests laufen im selben Stand wie die Attestation in der Windows-CI; ohne vollstaendiges Gruen wird keine `IsolationAttestation` erzeugt |

Zusatz fuer Linux (falls spaeter gefordert, siehe `isolation.py`): eigene Tests fuer Namespaces/Container; nicht Gegenstand dieses Entwurfs.

## 8. Quellen (offizielle Dokumentation, geprueft am 2026-11-07)

Die Angaben dieses Dokuments stuetzen sich auf die folgenden Herstellerseiten (Microsoft Learn bzw. MSRC). Aenderungen der Seiten nach diesem Datum sind nicht beruecksichtigt; vor einer Freigabe sind sie erneut zu pruefen.

- Job Objects: <https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects> (Stand der Seite: 2025-07-14); dazu `JOBOBJECT_BASIC_UI_RESTRICTIONS`, `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` in der Win32-API-Referenz.
- Restricted Tokens: <https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens>
- AppContainer isolation: <https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation> (Stand: 2025-07-08)
- Windows Sandbox: <https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/> (Stand: 2026-03-29)
- Windows Sandbox, `.wsb`-Konfiguration: <https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file>
- WSL: <https://learn.microsoft.com/en-us/windows/wsl/about>; Konfiguration (`wsl.conf`, `.wslconfig`): <https://learn.microsoft.com/en-us/windows/wsl/wsl-config> (Stand: 2026-10-16)
- Microsoft Security Servicing Criteria for Windows (welche Mechanismen als Sicherheitsgrenze gelten): <https://www.microsoft.com/en-us/msrc/windows-security-servicing-criteria>

**Nicht belegt / bewusst offen:** Funktioniert ein bestimmter fremder Coding-Agent in einem AppContainer? Lassen sich Zeit- und Plattenlimits in Windows Sandbox von aussen erzwingen? Kann ein Agent in WSL 2 die Haertung umgehen? Wie verhaelt sich Loopback-Blockade des AppContainers im Zielsystem? Diese Punkte beantworten erst die Abnahmetests.

## 9. Offene Besitzerentscheidungen

Diese Entscheidungen sind **nicht** getroffen; sie blockieren keinen weiteren freigegebenen Schritt (Entwurf ist abgeschlossen):

1. Ob und welche Option (A: AppContainer, B: Windows Sandbox, C: dedizierte Hyper-V-VM oder gehaertetes WSL 2) als Umsetzungs-Schritt freigegeben wird. Empfehlung des Entwurfs: C oder B fuer den ersten Prototyp (stabile, hypervisorbasierte Grenze, weniger Kompatibilitaetsprobleme als AppContainer); A nur, wenn ein konkreter Agent die Kompatibilitaet belegt; der Besitzer entscheidet.
2. Ob Windows Home als Zielsystem unterstuetzt werden muss (schliesst B und C aus).
3. Welcher Agent zuerst betrachtet wird und ob dessen LLM-Verkehr ausnahmsweise erlaubt wird (R2, Cloud-Datenuebertragung).
4. Der Umsetzungsschritt braucht eigene Freigabe (`approved: true`), Abhaengigkeits-Pruefung nach `docs/INTEGRATIONS.md` und die Windows-CI-Abnahme aus Abschnitt 7.

## 10. Verbindlicher Status

- Es gibt **keine** belastbare Sandbox. Externe Coding-Agenten sind ausgeschlossen und bleiben es, bis eine Option freigegeben, umgesetzt und durch Abschnitt 7 in der Windows-CI nachgewiesen ist.
- `winjob.py` und `winsec.py` sind Eindaemmung bzw. Dateischutz, keine Isolation; ein Notaus ist ebenfalls keine Isolation.
- Dieses Dokument aendert weder Code noch Konfiguration noch Sicherheitsdefaults.
