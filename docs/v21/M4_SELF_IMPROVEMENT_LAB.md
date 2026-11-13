# V2.1 M4 – Self-Improvement Lab (Konzept, keine Implementierung)

Stand: Entwurf zur Besitzer-Entscheidung. **Dieses Dokument ändert keinen Code.** Es gibt keine Freigabe für autonome Selbstmodifikation, keine für Codeausführung
vorgeschlagenen Codes und keine für das Aktivieren eines Vorschlags. Jede Aussage über Vorhandenes bezieht sich auf `claude/v2-integration` (Commit `7c2b4b7`).

## 0. Ausgangslage – was es schon gibt (nicht neu bauen)

Phase 15 (`src/jarvis/self_improvement/`, `docs/PHASE14_AUTONOMY.md`) ist ein **deaktivierter Vorschlagsworkflow**. Vorhanden und zu **erweitern, nicht zu ersetzen**:

| Baustein | Datei | Zweck | Stand |
|---|---|---|---|
| Beobachtung → Vorschlag | `analysis.py`, `manager.py` | wiederkehrende Probleme aus Zielmotor, Reparatur und Audit; Vorschläge mit Belegen | aktiv, wenn `self_improvement.enabled` |
| Zustandsmaschine | `state.py` | `DETECTED → PROPOSED → PREPARED → TESTED → READY_FOR_APPROVAL → APPROVED → ACTIVATED → ROLLED_BACK`, Seitenausgänge `FAILED/REJECTED/BLOCKED`, kein Überspringen | fertig |
| Ziel-Erlaubnisliste | `policy.py` (`ALLOWED_TARGETS`, `NEVER_TARGETS`, `ALLOWED_IMPORTS`, AST-Prüfung) | nur 11 sicherheitsneutrale Quelldateien; Berechtigungen, Werkzeuge, Konfiguration, `bootstrap.py`, dieses Paket selbst sind ausgeschlossen | fertig; ausdrücklich **Filter, keine Sicherheitsgrenze** |
| Review aus Git-Blobs | `review.py` | Änderungsliste aus `git diff-tree --raw`, Blobs aus der Objektdatenbank, SHA-1 neu berechnet, angezeigter Diff selbst erzeugt | fertig |
| Freigabe | `approval.py` (`ApprovalGate`) | eine einzige explizite Einmal-Zustimmung über den bestehenden `ConfirmationProvider`; ohne Oberfläche (`confirmation = deny`) nie freigebbar | fertig |
| Speicher | `store.py` | HMAC-signiertes `proposals.json`, Schlüsseldatei mit geprüfter ACL (`winsec.py`) | fertig |
| Ausführungssperre | `isolation.py` (`ExecutionGuard`, `IsolationAttestation`) | **kein Schalter** schaltet Ausführung frei; sieben nachzuweisende Eigenschaften | gesperrt, Produktion setzt nie eine Bescheinigung |
| Prozesseindämmung (Windows) | `winjob.py` | Job Object (Kill-on-close) – ausdrücklich *Eindämmung, keine Isolation* | vorhanden, nicht Teil des Nachweises |
| Gesperrte Schlüssel | `config.py` (`allow_prepare`, `allow_activation`, `repo_path`) | jeder andere Wert als der Standard wird beim Start abgelehnt | fertig |
| Schutz der Wächterdateien | `tests/support/protected_manifest.json` (N3-D) | Hash-Manifest für Berechtigungen, Notaus, Konfiguration und die zugehörigen Tests | fertig |

**Konsequenz:** M4 ist keine neue Fähigkeit „JARVIS ändert Code“, sondern die **Beschreibung der Strecke zwischen `PROPOSED` und `READY_FOR_APPROVAL`**, die heute
absichtlich nicht gebaut ist, plus der Beweis, dass die Produktivinstallation auf dieser Strecke nicht beschreibbar ist.

## 1. Leitfrage und Kernentscheidung

> Wie kann JARVIS Verbesserungsvorschläge erstellen, ohne seine eigene produktive Installation verändern zu können?

**Entscheidung (Vorschlag): „Nur Ausgabe, kein Rückweg“.** Das Lab erzeugt ausschließlich ein **Patch-Paket** (Daten) in einem Quarantäneverzeichnis. Das Paket wird von einem
**Menschen außerhalb von JARVIS** geprüft und in einem **getrennten Entwicklungs-Checkout** angewendet; der normale Weg (Branch `claude/*`, CI, Besitzer-Merge) bleibt der
einzige Weg in den Produktivstand. Es gibt **keinen** Pfad vom Lab zur laufenden Installation – weder durch JARVIS noch durch einen Hintergrundprozess.

Drei unabhängige Sperren, von denen jede allein genügen soll (Verteidigung in der Tiefe):

1. **Rechte:** Das Lab läuft nicht mit dem Konto der Installation (siehe 3.2). Die Installation ist für das Lab nicht beschreibbar, auch nicht durch einen Fehler in JARVIS.
2. **Datenfluss:** Der Ausgang ist ein Paket (Diff + Metadaten + Hashes) in `self_improvement.data_dir`, das laut Konfiguration **außerhalb** aller `allowed_roots` und
   `coding.workspace_roots` liegen muss. Kein JARVIS-Werkzeug darf es lesen *und* anwenden; Anwenden ist keine Tool-Aktion.
3. **Zustandsmaschine:** `ACTIVATED` bleibt unerreichbar (`allow_activation` reserviert). Das Lab endet bei `READY_FOR_APPROVAL`; die Freigabe bedeutet „Paket zur manuellen Übernahme
   freigegeben“, nicht „aktivieren“. (Offene Entscheidung D2: ob ein Zustand `EXPORTED` ergänzt wird.)

## 2. Architekturkonzept

```
 Beobachtungen (Journal, Audit, Zielmotor)            ← nur lesend, geschwärzt (SecretDetector inkl. Bearer)
          │  analysis.py
          ▼
   DETECTED ─► PROPOSED  (Text, Belege, Zielpfade aus ALLOWED_TARGETS)       ← heute vorhanden
          │
          │ ====== Grenze A: ab hier nur im Lab-Prozess (Abschnitt 3) =========  ← NICHT gebaut
          ▼
   PREPARED  (Arbeitskopie eines exportierten Commits, ohne .git, kein Netz)
          ▼
   TESTED    (Tests aus dem VERTRAUTEN Stand, nie vom Patch mitgebracht)
          ▼
   READY_FOR_APPROVAL ──► Patch-Paket (Abschnitt 5)  → Quarantäneverzeichnis
          │ ====== Grenze B: Mensch, außerhalb von JARVIS ======================
          ▼
   Besitzer prüft Paket → wendet es im Entwicklungs-Checkout an → Branch claude/* → CI (Linux + Windows) → Besitzer-Merge
```

Komponenten und Verantwortung:

- **Vorschlagsgeber** (vorhanden, `analysis.py`/`llm.py`): erzeugt Text und Änderungsplan. Er sieht nie die Freigabe, nie den Prozessstarter, nie die Schlüsseldatei.
- **Lab-Treiber** (neu, später): *einziger* Teil, der einen Prozess startet; läuft in der Isolation. Bekommt ein exportiertes Commit-Archiv und eine feste Befehlsliste, keine
  frei formulierten Befehle. Hat keinen Zugriff auf `ToolRegistry`, `PermissionEngine`, Konfiguration oder Speicher.
- **Prüfer** (vorhanden, `review.py` + `policy.py`): bewertet die *Blobs*, nicht den Diff-Text. Wird **außerhalb** des Lab-Prozesses ausgeführt, damit ein kompromittierter Lab-Prozess das Prüfergebnis nicht schreiben kann.
- **Paketbauer** (neu, klein): setzt aus geprüften Blobs das Paket zusammen und berechnet die Hashes; schreibt nur ins Quarantäneverzeichnis.
- **Freigabe** (vorhanden, `approval.py`): zeigt dem Besitzer die selbst erzeugte Darstellung und die Paket-Hashes.
- **Notaus-Anbindung** (neu, klein): ein Stopper wie bei `coding`/`computer` – beendet den Lab-Prozessbaum; Meldung ehrlich (`STOPPED/REQUESTED/FAILED`). Der Orchestrator-Guard (V2.1 Aufgabe 2) verhindert zusätzlich neue Lab-Läufe über Agenten.

Nicht-Ziele: kein Selbststart, kein Hintergrundziel, keine Änderung von Berechtigungen/Richtlinien/Konfiguration/Wächtertests, keine Änderung des Labs durch das Lab,
keine automatische Übernahme, kein Merge, keine Tags, keine Netzwerkzugriffe aus dem Lab, keine neuen Abhängigkeiten.

## 3. Isolationsmodell

### 3.1 Was „isoliert“ bedeuten muss (bereits in `isolation.py` festgelegt)
`unprivileged_user`, `no_host_credentials`, `no_network`, `no_main_repository`, `resource_limits`, `kills_all_descendants`, `platform_tests_passed`. Ein Git-Worktree ist **keine**
Sandbox (Hooks, Home-Verzeichnis, Netz, losgelöste Kindprozesse). Das Lab darf erst Code ausführen, wenn *jede* Eigenschaft je Plattform durch einen **dort laufenden Test** belegt ist.

### 3.2 Kandidaten (Bewertung, keine Auswahl – siehe D1)

| Plattform | Kandidat | trägt | trägt nicht / offen |
|---|---|---|---|
| Windows (Zielsystem) | Job Object + eingeschränktes Token (AppContainer oder Restricted Token) in separatem Benutzerprofil | Ressourcenlimits, Kill-on-close (`winjob.py` vorhanden), kein Zugriff auf fremde Profile | Netzsperre je Prozess ohne Firewall-Regel unklar; AppContainer-Start aus Python nicht erprobt; **Windows-Nachweis ausstehend** |
| Windows | Windows Sandbox / Hyper-V-Gast | starke Trennung, kein Hostzugriff | nicht in jeder Edition; Start langsam; Datenübergabe nur per Ordnerfreigabe zu prüfen |
| Linux (nur Zusatzprüfung) | `bubblewrap`/`nsjail` oder Container ohne Netz, Nutzer-Namespace | alle sieben Eigenschaften erreichbar | Linux ist kein Windows-Nachweis; Installation nur mit Freigabe |

Bis zur Entscheidung gilt: **kein Backend, `ExecutionGuard` bleibt gesperrt, `IsolationAttestation` wird von keinem Produktionscode erzeugt.**

### 3.3 Datenfluss in die und aus der Isolation
- **Hinein:** ein *exportierter* Commit (`git archive`, ohne `.git`, ohne Hooks), schreibgeschützt eingehängt; eine Arbeitskopie nur im flüchtigen Lab-Verzeichnis. Keine Umgebungsvariablen außer einer festen Liste; keine Schlüssel, kein Home.
- **Heraus:** genau ein Ergebnisordner mit Textdateien (Diff-Blobs, Testprotokoll gekürzt und geschwärzt). Der Prüfer liest ihn **als Daten**; nichts daraus wird importiert oder ausgeführt.
- **Lab → Installation:** es gibt keinen Pfad. Die Installation liegt in einem für das Lab-Konto nicht lesbaren/schreibbaren Verzeichnis; als Installationsvoraussetzung (D4) empfohlen: Programmdateien schreibgeschützt (ACL), Daten und Konfiguration getrennt.

## 4. Sicherheitsgrenzen (verbindlich, auch für spätere Umsetzung)

1. Das Lab ändert **nie**: `permissions/`, `tools/`, `coding/`, `browser/`, `computer/`, `core/`, `agents/`, `llm/`, `interface/`, `self_improvement/`, `voice/`, `redaction.py`, `config.py`, `bootstrap.py`, `errors.py`, `logging_setup.py`, `config/jarvis.toml`, `.github/`, `.claude/`, Wächtertests, `protected_manifest.json`. (Heute schon in `NEVER_TARGETS` und im Manifest; die Liste darf nur wachsen.)
2. Die Erlaubnisliste wächst **nur** durch Besitzerentscheidung per normalem Review (D6), nie durch einen Vorschlag.
3. Tests, die ein Vorschlag „bestätigen“, stammen **aus dem vertrauten Stand**; vom Patch mitgebrachte oder geänderte Tests zählen nicht (verhindert „Test abschwächen, damit grün“).
4. Kein Netz im Lab; Netzzugriff für Modelle nur im Vorschlagsgeber über die bestehende Routing-/Budget-Schicht mit geschwärzten Eingaben.
5. Keine Freigabe ohne sichtbaren, selbst erzeugten Diff und die Paket-Hashes; eine Freigabe gilt für **genau ein** Paket (Hash), nicht für „diesen Vorschlag“.
6. Alles über die bestehenden Kontrollstellen: Werkzeuge über `ToolRegistry.execute → PermissionEngine`; kein zweiter Freigabeweg; Notaus sperrt neue Läufe und beendet laufende.
7. Standardmäßig aus; keine produktive Aktivierung; reservierte Schlüssel bleiben abgelehnt.
8. Das Lab hat kein Gedächtnis über Läufe hinaus außer dem signierten Speicher; es lernt nichts „in die Installation“.

## 5. Patch-Review-Workflow

| # | Schritt | Wer | Ergebnis / Gate | Scheitert bei |
|---|---|---|---|---|
| 1 | Beobachtung wird zum Vorschlag | Analyse (vorhanden) | `PROPOSED` mit Belegen, Zielpfaden ⊆ `ALLOWED_TARGETS` | Pfad außerhalb → `BLOCKED` |
| 2 | Änderung vorbereiten | Lab-Treiber in Isolation | Arbeitskopie, Edits aus dem Vorschlag, **kein** frei generierter Befehl | Isolation nicht bescheinigt → `ExecutionDisabled` (Normalzustand heute) |
| 3 | Blob-Prüfung | `review.py` außerhalb der Isolation | nur erlaubte Dateien, reguläre Modi, UTF-8, AST-Prüfung des Gesamtmoduls | irgendein Zweifel → `BLOCKED` (manuelle Prüfung) |
| 4 | Tests aus vertrautem Stand | Lab-Treiber | jede Pflichtstufe ausgeführt **und** bestanden; übersprungen = nicht bestanden | Fehler → `FAILED` (Wiederholung nur mit neuen Edits, begrenzt) |
| 5 | Paket bauen | Paketbauer | `bundle.json` (Vorschlags-ID, Basis-Commit, Blob-IDs alt/neu, SHA-256 von Diff und Blobs, Teststand, Risikohinweis), `patch.diff`, `report.txt`; Datei-/Verzeichnisrechte nur für den Besitzer | Schreibfehler → kein Paket |
| 6 | Freigabe zur Übernahme | `ApprovalGate` | Besitzer sieht erzeugten Diff + Hashes; einmalig, kein Sitzungs-„Ja“ | Nein/Timeout/Fehler → `REJECTED` |
| 7 | Übernahme | **Mensch**, außerhalb von JARVIS | `git apply --check`, dann Branch `claude/*` im Entwicklungs-Checkout | Hash ≠ Paket → abbrechen |
| 8 | CI und Merge | CI (Linux + Windows), Besitzer | normaler Ablauf; Windows-Nachweis nötig | rot → zurück zu Schritt 1 |

Prüfliste für den Besitzer (im Bericht jedes Pakets): Betrifft ein Pfad Sicherheitslogik? Wird ein Test geändert oder entfernt? Neue Importe? Neue Netz-/Datei-/Prozessaufrufe?
Ändert sich ein Standardwert? Erklärt der Text die Änderung vollständig? Stimmen die Hashes? Gab es Warnungen der AST-Prüfung?

## 6. Rollback-Konzept

Weil JARVIS nie aktiviert, ist Rollback überwiegend das **Verwerfen** vor der Übernahme:

| Ebene | Auslöser | Maßnahme | Wer |
|---|---|---|---|
| Lab-Lauf | Fehler, Timeout, Notaus | Prozessbaum beenden (alle Nachkommen), Arbeitsverzeichnis vernichten, Zustand `FAILED` | Lab-Treiber / Notaus-Stopper |
| Vorschlag | Besitzer lehnt ab | `REJECTED`, Paket gelöscht oder archiviert, nichts übernommen | Besitzer |
| Übernommener Patch | Regression nach Merge | `git revert` des Merge-Commits im normalen Ablauf; vor jedem Release ein bekannter guter Stand (Tag nur durch den Besitzer) | Besitzer |
| Speicher | beschädigtes `proposals.json` | HMAC-Prüfung schlägt an (`IntegrityError`, fail closed); gesicherte Kopie vor jedem Zustandswechsel (zu entscheiden, D5) | System, Besitzer |
| Notaus | Latch aktiv | Lab-Stopper beendet den Lauf, neue Läufe werden nicht angenommen (Orchestrator-Guard), Reset nur durch den Besitzer | Notaus |

Der Zustand `ROLLED_BACK` der Zustandsmaschine bleibt für **spätere** Aktivierung reserviert; in M4 wird er nicht erreicht.

## 7. Teststrategie

Grundsätze: Rot zuerst; keine Tests abschwächen; **kein Skip als Bestanden**; Linux-Ergebnisse sind kein Windows-Nachweis; Isolationseigenschaften nur auf der Plattform belegen, auf der sie gelten.

1. **Rein (bereits vorhanden, erweitern):** Zustandsmaschine, `policy.py`, `review.py` mit Angriffsbeispielen (Unicode-Pfade, Moduswechsel, Symlinks, `.gitattributes`-Tricks, große Dateien, Nicht-UTF-8, NUL).
2. **Negativ-Fähigkeiten (neu):** Kanarienvogel-Tests im Lab: Datei außerhalb schreiben, Loopback-Verbindung öffnen, Umgebungsvariable lesen, Elternprozess abfragen, `.git/hooks` anlegen, losgelösten Kindprozess starten – **jeder Versuch muss scheitern**; danach Hash-Vergleich des gesamten Installationsbaums (unverändert).
3. **Ressourcen:** CPU-, Speicher-, Zeit-, Ausgabe-, Prozessanzahl-Grenzen mit absichtlichen Verletzern (Fork-Bombe in der Isolation, Endlosschleife, 1-GB-Ausgabe).
4. **Nachkommen:** kein Prozess überlebt Timeout/Notaus (Windows: Job Object; Linux: Namespace).
5. **Rote-Karte-Korpus:** bösartige Patches (Backdoor in erlaubter Datei, Import-Umgehung, dynamische Attributzugriffe, Test-Abschwächung, Wächterdatei-Änderung); jeder muss `BLOCKED` ergeben. Neue Fälle kommen aus echten Funden, nie aus Lockerungen.
6. **Ende-zu-Ende mit Attrappe:** vollständiger Ablauf Vorschlag → Paket mit einem *Fake-Backend*, das die Schnittstelle erfüllt; beweist die Verdrahtung, nicht die Isolation.
7. **Selbstschutz:** Manifest-Test (N3-D) deckt weiterhin die Wächterdateien; ein Test stellt sicher, dass das Lab-Paket keine Datei aus `NEVER_TARGETS` oder dem Manifest als Ziel zulässt.
8. **Notaus:** Latch aktiv → Lab startet nicht; Latch während des Laufs → Prozessbaum beendet, Bericht ehrlich; Reset → kein stilles Wiederaufnehmen.
9. **CI:** Windows-Lauf ist Pflicht für jede Isolationsaussage („Windows-Nachweis ausstehend“, bis grün). Playwright/GUI-Themen sind hier nicht beteiligt.

## 8. Bedrohungsanalyse

Angreifer: (a) manipulierte Eingaben (Webseiten, E-Mails, Dateien, die in Beobachtungen oder Journal gelangen), (b) fehlerhaftes oder getäuschtes Modell, (c) bösartiger/fehlerhafter Vorschlagstext, (d) lokaler Prozess mit Benutzerrechten, (e) versehentliche Fehlbedienung. Nicht im Modell: Angreifer mit Administratorrechten auf dem Host.

| ID | Bedrohung | Auswirkung | Gegenmaßnahme (vorhanden → V) / (neu → N) | Rest |
|---|---|---|---|---|
| T1 | Prompt-Injection über Beobachtungen/Journal lenkt den Vorschlag | schädlicher Vorschlagstext | Schwärzung, Daten statt Anweisungen (V); Ziele nur aus `ALLOWED_TARGETS` (V); Mensch gibt frei (V) | Täuschung des Besitzers durch überzeugenden Text → T12 |
| T2 | Hintertür im Patch einer erlaubten Datei | Schaden nach Übernahme | AST-Prüfung, Import-Erlaubnisliste, Blob-Review (V); menschliche Prüfung, CI (V) | statische Prüfung ist ein Filter, kein Beweis |
| T3 | Diff-Verschleierung (`-diff`, Binär-Attribut, Unicode) | Prüfer sieht anderes als Inhalt | Review aus Blobs, selbst erzeugter Diff (V) | – |
| T4 | Austausch zwischen Prüfung und Freigabe (TOCTOU) | geprüft ≠ freigegeben ≠ angewendet | Freigabe bindet an Paket-SHA-256 und Blob-IDs; Anwenden prüft Hash (N) | – |
| T5 | Ausbruch aus dem Lab (Hooks, Home, Netz, losgelöste Prozesse) | Schreibzugriff auf Installation, Datenabfluss | Ausführung gesperrt (V); Isolationsnachweis je Plattform (N); Kanarienvogel-Tests (N) | bis zum Nachweis: kein Lab-Lauf |
| T6 | Diebstahl/Fälschung des Speicherschlüssels | gefälschte Vorschläge | Schlüssel außerhalb `data_dir`, ACL-Prüfung (V); Lab-Konto ohne Zugriff (N) | Host-Kompromittierung |
| T7 | Manipulation von `proposals.json` | falscher Zustand | HMAC, `IntegrityError` fail closed (V) | – |
| T8 | Freigabe ohne Mensch (headless, Skript, Modell) | Selbstfreigabe | `ApprovalGate` nur aus UI, `confirmation = deny` ⇒ nie freigebbar (V) | – |
| T9 | Das Lab schwächt Wächter, Tests oder sich selbst | Sicherheitsverlust | `NEVER_TARGETS`, Hash-Manifest, Tests nur vom vertrauten Stand (V/N) | Manifest-Änderung durch Besitzer ist bewusst möglich |
| T10 | Ressourcenerschöpfung | Absturz/Hänger | Limits, Timeout, Kill aller Nachkommen (N) | – |
| T11 | Neue Abhängigkeit/Lieferkette | fremder Code | nur Standardbibliothek-Erlaubnisliste (V); keine Installation im Lab (N) | – |
| T12 | Sozialtechnik gegenüber dem Besitzer | Freigabe aus Vertrauen | festes Prüfformat, Risikohinweis, Hashes, keine Freitext-Überzeugung in der Freigabemaske (N) | menschliche Fehlentscheidung |
| T13 | Dauerhafte Spuren im `data_dir` | Persistenz | Verzeichnis außerhalb der erlaubten Wurzeln, nur Daten, nie ausgeführt (V/N) | – |
| T14 | Lab läuft trotz Notaus weiter | unkontrollierter Prozess | Notaus-Stopper, Orchestrator-Guard, Latch im Pfad jeder Aktion (V + N) | nicht kooperierende Prozesse: ehrlich als `REQUESTED/TIMEOUT` melden |
| T15 | Audit-Umgehung / Logleck | fehlende Spur, Geheimnis im Log | jede Stufe als Audit-Ereignis (nur Zahlen/IDs); Schwärzung inkl. Bearer (V/N) | – |
| T16 | Schleichende Ausweitung der Erlaubnisliste | indirekte Lockerung | Änderung nur durch Besitzer-Review; Test pinnt die Liste (N) | – |

## 9. Was in M4 *nicht* entschieden ist (offene Entscheidungen)

- **D1** Sandbox-Backend je Plattform (Abschnitt 3.2) und wer es beschafft/installiert (Installation nur mit Freigabe).
- **D2** Zusätzlicher Zustand `EXPORTED`/Paket statt `ACTIVATED`? Empfehlung: ja, `ACTIVATED` bleibt unerreichbar.
- **D3** Ort des Quarantäneverzeichnisses und Aufbewahrungsdauer (Empfehlung: `data_dir`, Besitzerrechte, 30 Tage).
- **D4** Installationsvoraussetzung „Programmdateien schreibgeschützt, Konto des Labs ohne Rechte“ als dokumentierte Pflicht.
- **D5** Gesicherte Kopie des Speichers vor Zustandswechseln.
- **D6** Verfahren zum Erweitern von `ALLOWED_TARGETS` (Besitzer-PR mit Begründung).
- **D7** Darf das Lab jemals Tests des Vorschlags ausführen? Empfehlung: nein; nur vertraute Tests, nach Attest und grünem Windows-Lauf.
- **D8** Modellnutzung im Vorschlagsgeber (Budget, Routing, geschwärzte Eingaben) – bestehende `LLM_ROUTING`/`LLM_BUDGET`-Regeln gelten.

## 10. Umsetzungsreihenfolge (erst nach ausdrücklicher Freigabe je Schritt)

1. Zustand/Paketformat (`bundle.json`) und Paketbauer – rein, ohne Prozesse, vollständig testbar.
2. Notaus-Stopper und Orchestrator-Guard für Lab-Läufe (Guard ist mit V2.1 Aufgabe 2 vorhanden).
3. Kanarienvogel-Testsuite und Rote-Karte-Korpus – ohne Backend lauffähig gegen eine Attrappe.
4. Sandbox-Backend je Plattform **mit** eigenem Windows-Test; erst dann Attest.
5. Verdrahtung nur in `bootstrap.py`; Standard aus.

Bis Schritt 4 abgeschlossen und der Windows-Lauf grün ist, bleibt alles hier Beschriebene ein Konzept.
