# Release-Plan: JARVIS als Windows-PC-Assistent (Zielmarke 21.11.2026)

Stand: nach PR #69 (LLM-Kette freigegeben, Kette gestartet). Alle Schätzungen sind **Planungsannahmen**, keine Zusagen: Sie hängen von der Merge-Geschwindigkeit des Besitzers, der Windows-CI (rund 25 Minuten je PR) und davon ab, dass die Routine die offiziellen Quellen erreicht. Nichts hier behauptet erfolgreiche Tests.

## Was schon läuft (belegt auf `main`)
Core mit Planner (LLM-JSON mit Vorlage als Rückfall), Aufgaben-System, Permission-Engine (GREEN/YELLOW/RED, Notaus, Sitzungsbudget, Audit), Multi-Agent-Orchestrierung, Goal Engine (regelbasiert, mit LLM-Replanning), Self-Repair, Browser-Agent (Playwright, bestätigte Einzelschritte), Computer-Steuerung (Bildschirm, Maus, Tastatur, Fenster, Programme; Windows-first), **lesende** UI-Automation (Provider und Tool `ui`, echt auf Windows getestet), Coding-Agent (ein bestätigter Workspace, hash-geschützt, Tests ohne Shell), Research-Agent (liest vorgegebene Seiten, klassifiziert FACT/INFERENCE/OPINION, kein Suchdienst), Business- und Finance-Agent (nur Rechnen und Entwürfe, Paper-Trading), Memory (SQLite, lokale Suche), Verlauf, Voice (STT/TTS-Schnittstellen, Barge-in, Hotword-Baustein), Tk-GUI, `jarvis doctor`.

## Kritischer Pfad und Engpässe
1. **Es gibt noch keinen durchgehenden Assistenten-Ablauf**: Text oder Sprache → LLM-Planung → Werkzeugwahl → bestätigte Ausführung → Ergebnis. Die Teile existieren, die Verkabelung mit einem echten LLM (Provider, Planung) fehlt. Das ist der kritische Pfad: LLM-Provider (Kette läuft) → LLM-Zielplanung → Ablauf Ende zu Ende.
2. **Durchsatz der Automatik:** ein aktiver Auftrag zugleich, höchstens 5 Aufträge je Kette, Tageslimit `JARVIS_MAX_JOBS_PER_DAY` (Standard 10, hart 50). Die 16 freigegebenen Schritte brauchen daher mindestens drei Ketten; bei Standard-Tageslimit ist das der Engpass. Empfehlung an den Besitzer: Variable auf 30 heben (liegt in deiner Hand, nicht in meiner).
3. **Besitzer-Merges:** Schritte, die `bootstrap.py` oder andere geschützte Pfade ändern, mergt der Besitzer. Zwei Schritte haben außerdem eine eingebaute Bibliotheks-Freigabe (siehe unten).
4. **Echte Parallelität** gibt es in der Kette nicht. Parallel arbeiten geht nur mit zusätzlichen Sitzungen (je Strang eine eigene Branch/PR); das starte ich erst, wenn die Freigaben gemergt sind.

## Fünf Arbeitsstränge

### A. Kern: LLM und Planung (kritischer Pfad)
- **Wiederverwendbar:** LLM-Abstraktion (`mock`/`openai`/`anthropic`), Planner, Goal Engine, Orchestrator, Verlauf, Gedächtnis.
- **Fehlt:** OpenAI-kompatibler Provider (lokal und Cloud), Routing nach Datenschutz, LLM-gestützte Zielzerlegung, ein Ende-zu-Ende-Ablauf mit Bedienoberfläche.
- **Abhängigkeiten:** `llm-compat-vetting` → `llm-compat-provider`, `llm-routing-design` → `llm-routing-policy` (alle freigegeben, Kette läuft) → `llm-goal-planning` (neu freigegeben, hängt jetzt zusätzlich von `llm-routing-policy` ab).
- **Aufgaben:** die vier LLM-Schritte; `llm-goal-planning`; danach (neuer Eintrag, braucht Freigabe) `assistant-e2e`: Eingabe → Planung → Agenten → Bestätigung → Ergebnis in CLI und GUI.
- **Schätzung:** LLM-Kette ca. 1 bis 2 Tage (läuft), Planung +1 bis 2 Tage, Ende-zu-Ende ca. 2 bis 3 Tage nach der Planung.
- **Freigaben:** LLM-Kette erteilt; `llm-goal-planning` (neu, sicherheitskritisch); Schritt 4 verdrahtet in `bootstrap.py` (Merge durch dich); `assistant-e2e` (neuer Eintrag).

### B. Windows-Bedienung
- **Wiederverwendbar:** Controller, Sperrliste, Notaus, Bestätigungsdialoge, UIA-Provider und -Tool (lesend), Fenster- und Screenshot-Werkzeuge, Maus/Tastatur.
- **Fehlt:** Aktionen über UIA-Muster, Anbindung an den Computer-Agenten, Ende-zu-Ende-Test mit Aktionen.
- **Abhängigkeiten:** `uia-tools-readonly` (erledigt) → `uia-actions` → `uia-agent-integration` → `uia-windows-e2e`.
- **Aufgaben:** Invoke, Wert setzen, Auswahl, Umschalten, Fokus je als eigene bestätigte Aktion mit Prüfung danach; Agent bevorzugt UI-Baum, Bildschirmfoto nur als Rückfall; Windows-Test an Notepad.
- **Schätzung:** ca. 3 bis 5 Tage; Aktionen an modernen Anwendungen und Windows 11 sind ungeprüft und können mehr Zeit brauchen.
- **Freigaben:** alle drei Schritte neu (sicherheitskritisch: steuert den PC).

### C. Wissen und Sprache
- **Wiederverwendbar:** Research-Agent, URL-Richtlinie, Extraktion, Voice-Schnittstellen (STT/TTS, Barge-in, Hotword-Baustein), Memory.
- **Fehlt:** Suchquelle, bessere Textextraktion, lokale Spracherkennung, Sprachende-Erkennung.
- **Abhängigkeiten:** `stt-vetting` → `stt-local-provider` → `stt-vad-endpointing`; `research-vetting` → `research-search-interface` → `research-extract-backend` und `research-search-provider`.
- **Aufgaben:** Prüfberichte (offizielle Quellen), Provider hinter den vorhandenen Schnittstellen, Standard bleibt aus.
- **Schätzung:** Sprache ca. 2 bis 3 Tage, Recherche ca. 3 bis 4 Tage.
- **Freigaben:** sieben Schritte neu. **Zwei eingebaute Besitzer-Stopps**: `stt-local-provider` und `research-extract-backend` starten erst, wenn das Prüfdokument (`docs/integrations/stt-local.md`, `docs/integrations/research.md`) die Entscheidung `nehmen` und eine Zeile `Besitzer-Freigabe: <Datum>` trägt; bei `research-search-provider` wählst du die Suchquelle.

### D. Coding und Dateien
- **Wiederverwendbar:** Coding-Agent und -Controller (Workspace, Pfadschutz, hash-geschützte Änderungen, Tests), Self-Repair, Git lesend.
- **Fehlt:** Das Modell entwirft Änderungen selbst; allgemeine Datei-Werkzeuge (lesen, anlegen, ändern, verschieben, aufräumen in bestätigten Ordnern) außerhalb von Code-Projekten.
- **Abhängigkeiten:** `llm-goal-planning` → `coding-llm-edits`; Datei-Werkzeuge sind neu und unabhängig.
- **Aufgaben:** `coding-llm-edits` (Änderungsentwürfe, jede Änderung bestätigt, Tests vor und nach, nie das JARVIS-Repository); neuer Eintrag `files-tools`.
- **Schätzung:** Coding ca. 2 bis 3 Tage nach der Planung; Datei-Werkzeuge ca. 2 Tage.
- **Freigaben:** `coding-llm-edits` neu (sicherheitskritisch); `files-tools` (neuer Eintrag, schreibt Dateien).

### E. Dokumente, E-Mail, Medien, Geschäftsprozesse
- **Wiederverwendbar:** Business- und Finance-Agent, Entwurfsdokumente (`mail-design`, `office-design`, `media-design` sind Backlog-Schritte, aber nicht freigegeben), Redaktion, Bestätigungsmechanik.
- **Fehlt:** alles Umsetzende: E-Mail lesen und Entwürfe (Senden nur je Nachricht bestätigt), Tabellen, Texte und Präsentationen (openpyxl, python-docx, python-pptx als Kandidaten), Medienbearbeitung (FFmpeg mit festen Argumentlisten), Content-Agent.
- **Abhängigkeiten:** Entwurfsdokumente zuerst, dann je Bereich ein Prüfbericht und ein Provider; E-Mail hängt am Routing (Datenschutz).
- **Aufgaben:** Dieser Strang hat noch keine freigegebenen Schritte. Vorschlag neuer Einträge: `mail-provider`, `office-docs`, `media-ffmpeg`, `content-agent`.
- **Schätzung:** nach Freigabe je Bereich ca. 3 bis 5 Tage; früheste Nutzbarkeit Mitte November, wenn die Einträge bis ca. 8. November freigegeben sind.
- **Freigaben:** alle Einträge neu; das Versenden einer E-Mail bleibt je Nachricht bestätigungspflichtig und wird nie automatisch freigegeben.

## Meilensteine (Planungsannahme, kein Versprechen)
| Meilenstein | Inhalt | frühestens |
|---|---|---|
| M1 | LLM-Provider und Routing, lokale Sprache, Recherche mit Suchquelle (alles standardmäßig aus, konfigurierbar) | ca. 8. bis 10. November |
| M2 | LLM-Zielplanung, UI-Aktionen mit Einzelbestätigung, Agenten-Anbindung | ca. 12. bis 15. November |
| M3 | Ende-zu-Ende-Assistent in CLI und GUI, Coding mit Änderungsentwürfen, Datei-Werkzeuge | ca. 15. bis 18. November |
| Release-Kandidat | Dokumente und E-Mail-Entwürfe, Härtung, Windows-Nachweise, Installationsanleitung | ca. 19. bis 21. November |

Der erste nutzbare Gesamtstand ist M3. Verzögerungen entstehen vor allem durch ausstehende Besitzer-Merges, die zwei Bibliotheks-Stopps (Sprache, Recherche) und die Tageslimits der Automatik.

## Konkrete Rechte und Risiken der in diesem PR freigegebenen Bereiche
| Bereich | Neue Rechte (nur mit Einzelbestätigung, Notaus, Budget) | Risiken | Gegenmaßnahmen im Code |
|---|---|---|---|
| UI-Aktionen (`uia-actions`, `uia-agent-integration`, `uia-windows-e2e`) | Steuerelemente fremder Programme per UI-Automation-Muster bedienen: Invoke, Wert setzen, Auswahl, Umschalten, Fokus | Falsches Fenster oder Steuerelement, Datenverlust, unbeabsichtigtes Absenden; Befehle in Fensterinhalten (Prompt-Injection); Bestätigungsmüdigkeit | jede Aktion YELLOW, nie Sitzungsfreigabe für schreibende Aktionen vorgesehen; Neuprüfung des Ziels vor der Ausführung; Passwortfelder und gesperrte Fenster nie; Zustand wird danach gelesen und ehrlich gemeldet; der Test an Notepad läuft nur auf dem CI-Runner |
| Lokale Sprache (`stt-*`) | Audio vom Mikrofon lokal erkennen | Lizenz der Modelle, Lieferkette, Audio bleibt lokal | nur Wheels mit Hash, kein Modell-Download zur Laufzeit, Besitzer-Freigabezeile im Prüfdokument |
| Recherche (`research-*`) | Suchanfragen an eine gewählte Suchquelle senden; Webseiten lesen | Datenabfluss der Suchbegriffe, Kosten, Prompt-Injection aus Webinhalten | Schlüssel nur aus der Umgebung, Rate-Limit, URL-Richtlinie, Inhalte sind Daten; Quelle wählt der Besitzer |
| Zielplanung (`llm-goal-planning`) | Ein LLM zerlegt Ziele in Schritte | Zielinhalte gehen an ein Cloud-Modell; ein fehlgeleiteter Plan | Plan darf keine neuen Fähigkeiten, Tools oder Agenten hinzufügen; harte Limits (höchstens 50 Schritte, 5 Versuche); jede Aktion läuft weiter durch die Engine; Routing-Richtlinie entscheidet Cloud oder lokal |
| Coding mit Änderungsentwürfen (`coding-llm-edits`) | Das Modell entwirft Änderungen in einem bestätigten Workspace | fehlerhafter oder schädlicher Code, Quelltext geht an ein Cloud-Modell | nur der bestätigte Workspace, nie das JARVIS-Repository, hash-geschützt, jede Änderung bestätigt, Tests vor und nach, standardmäßig aus |

**Nicht freigegeben und nicht Teil des PR:** `audit-hash-chain`, `cli-confirm-timeout`, `smartphone-api-design` (bleiben gesperrt), MCP, E-Mail, Office, Medien, Datei-Werkzeuge, OS-Sandbox. Irreversible externe Aktionen (E-Mail senden, Löschen, Bezahlen, Veröffentlichen) werden nie automatisch ausgeführt oder freigegeben.

## Ausführung nach dem Merge
Die Reihenfolge, in der die Automatik die Schritte wählt (Reihenfolge in `backlog.json`): LLM-Kette (läuft), Sprache, Recherche, UI-Aktionen, Zielplanung, Coding. Start jeder weiteren Kette: Actions → "Trigger Claude Code Routine" mit `backlog_item = next`, `auto_continue = true`, `chain_budget = 5`; sie stoppt an den Besitzer-Merges und den zwei Bibliotheks-Stopps und setzt nach dem Merge fort.
