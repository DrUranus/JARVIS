# V2-Folgeplan nach #186 (Stand 2026-11-15; Lesestand, keine neue Architektur)

Grundlage: `docs/V2_ARCHITEKTUR.md`, `V2_BACKLOG.md`, `V2_TESTPLAN.md`, `PHASE14_AUTONOMY.md`, `BACKLOG.md` und Quellcode-Lesung (`agents/`, `goals/`, `journal/`). Unklares ist als „unklar“ markiert; nichts davon ist freigegeben oder umgesetzt, was nicht ausdrücklich so steht. Smartphone und Cloud-Infrastruktur sind ausgeschlossen.

## 1. Stand
* **Umgesetzt (Branch `claude/v2-186-windows-abnahme`, CI auf der Basis `7c2b4b7` grün):** WP01 typisierte Artefakte (+WP01b Verdrahtung, Standard aus), WP02a Kostenmodell (nicht durchgesetzt), WP02b Agent-Budgets (Standard aus), WP03 gemischte Aufträge, WP03b mehrere URLs/Speicherwunsch als „incomplete“, WP04 Business-Finder, WP05b Windows-TTS, WP06 UIA-Zuverlässigkeit, WP07a/b/c NEXUS-Ansichten/Zeitleiste/Freigabe-Panel, WP08 QA/Testplan, WP10 Integrationstests E1–E12, N3-D/N3-B (Hash-Manifest geschützter Dateien). Ob alle zugehörigen PR-Nummern gemergt sind: unklar (nur Branch-Commits belegt; #258 ist Draft „NICHT mergen“).
* **Gesperrt / Gates:** G0 (V1-Abnahme #186) ist der Release-Blocker; G5/G7 brauchen Owner-Zielwerte; G9 interaktive Abnahme; G10 Owner-Freigabe. Release-Freeze V1 bis 21.11.2026. Phase-14-Teilziel 5 (Selbststart, Hintergrund-/zeitgesteuerte Ziele, Fernsteuerung) bleibt gesperrt; Controller-Backlog hat „kein freigegebener Schritt offen“. Three.js im NEXUS gesperrt. MCP-SDK, OpenHands, pypdf (V2-11) nicht freigegeben. Die „B1-Bibliotheksentscheidungen“ sind in den Repository-Dokumenten **nicht auffindbar** (unklar): nicht vorwegnehmen.
* **Harte Grenzen:** `max_steps` ≤ 50, Versuche ≤ 5, Agent-Recovery ≤ 3, `MAX_REPLANS` = 2, PermissionEngine, Not-Aus, Budget, `config/jarvis.toml`-Defaults.

## 2. Belegte Lücken bei mehrstufigen Aufgaben
| Bereich | Befund (Datei) | Auswirkung |
|---|---|---|
| Planung | `goals/planner.py` `_combine`: gemischte Aufträge sind unabhängige Zweige + eine Auswertung; keine Datenübergabe (z. B. Recherche -> Datei schreiben); ein nicht planbarer Teil lehnt den ganzen Auftrag ab | Ergebnisse fließen nicht zwischen Teilen |
| Agentenwahl | `agents/planner.py`: nur Stichwortregeln, Schwelle 3, Gleichstand = kein Agent; Router-LLM in `bootstrap.py` mit `llm=None` verdrahtet | Fehlklassifikation bei Mischformulierungen (in #186 bereits für Dateianfragen entschärft) |
| Übergaben | `agents/orchestrator.py` ~309–313: nur Ergebnisse erfolgreicher Vorgänger, roh kopiert; nur Business/Finance nutzen `parent_results`; Artefakte nur vom Research-Agent | Folgeagenten ignorieren Vorgängerergebnisse |
| Teilerfolge | `orchestrator.py`/`goals/engine.py`: scheitert ein Vorgänger, werden Nachfolger BLOCKED; Teilergebnisse nur als Zähler (`engine.py` ~602) | Nutzer sieht nicht, was schon erledigt war |
| Fehlerlogik | `agents/recovery.py` (`RecoveryRunner`) ist **nirgends verdrahtet**; `goals/policy.py` hat eigene, abweichende Retry-Codes; `target_changed` fehlt dort | zwei nicht abgestimmte Regeln; in #186 wurde die konkrete Wiederholungsschleife bei Eingabefehlern (`invalid_input`) im Datei-Adapter behoben |
| Ergebnisprüfung | `goals/evaluator.py` ~121–135: prüft nur „Vorgänger erfolgreich, Ausgabe nicht leer, kein `ok:false`“ | keine inhaltliche Zielprüfung, keine Quellenbewertung (V2-10/V2-01 nicht verdrahtet) |
| Wiederaufnahme | `journal/recorder.py` Pull-Modell (Sync über Pump-Hook), speichert pro Schritt nur Kurztext; `journal/resume.py`: nur unterbrochene Ziele (`PENDING/PLANNING/RUNNING/WAITING`), erledigte Schritte werden übersprungen und Abhängigkeiten auf sie gelöscht, Neuplanung = neues Ziel | Ergebnisse erledigter Schritte fehlen nach Resume; FAILED/BLOCKED nicht fortsetzbar |
| Randfall | `orchestrator._trim` (max_history 200) kann Vorgänger-Records entfernen -> „unknown_dependency“ | unbewiesen (nicht reproduziert): nur bei sehr langen/parallelen Läufen denkbar |
Alles standardmäßig aus (`[agents]`, `[goals]`); echte LLM-Planqualität ungetestet (Standard `mock`).

## 3. Arbeitspakete (Reihenfolge und Abhängigkeiten)
| Nr. | Paket | Inhalt | Freigabe nötig? | Abhängig von |
|---|---|---|---|---|
| P0 | **#186 abschließen** | Sammelabnahme (`ABNAHME_186_MATRIX.md` §4), CI `pr-tests`/`uia-compat`, Integration (Commits A/B) | Push/PR/CI-Start: Owner | – |
| P1 | Sprache produktiv | S2-Messwerte, Entscheidung base/medium nach echten Aufnahmen (`--real`), optional echtes LLM (`nexus.live.example.toml`) | Schlüssel/Kosten: Owner | P0 |
| P2 | Konsistenz der Fehlerlogik | gemeinsame, getestete Retry-Code-Tabelle `recovery.py` ↔ `goals/policy.py` (zunächst nur ein Test, der die Abweichung sichtbar macht) | nein (nur Tests/Konstanten, keine geschützten Pfade) | P0 |
| P3 | Teilergebnisse sichtbar | Zusammenfassung bei Abbruch durch Abhängigkeit zeigt erledigte Schritte (reine Darstellung: `goals/engine.py` `_conclude`, `interface/goal_text.py`) | nein | P0 |
| P4 | Evaluator strenger (additiv) | leere/triviale Ausgaben je Agententyp melden, Tests je Agent | nein | P3 |
| P5 | Plan-Harness erweitern (V2-02) | mehrstufige Goldenfälle (nur Tests) | Golden-Änderung wie in E7 freigegeben | P0 |
| P6 | Journal-Ausgabekurzfassung | redigierte, begrenzte Ergebnisse je Schritt mitspeichern, damit Resume Kontext hat | **ja** (persistierte Inhalte, Datenschutz) | P0, P2 |
| P7 | Artefakt-Verdrahtung für weitere Agenten (E5) / Planer-Freigabe (E7) / Kostenbudget (E6) | Datenübergabe zwischen Agenten | **ja** (Besitzerentscheidungen E5/E6/E7) | P0 |
| P8 | Quellenbewertung anbinden (V2-10) | `research/credibility.py` ist fertig, unverdrahtet | **ja** (Besitzerfrage 2, `V2_ARCHITEKTUR` §5) | P7 |
| P9 | Wiederaufnahme ausbauen | FAILED/BLOCKED fortsetzen, Ergebnisse erledigter Schritte beibehalten | **ja** (Architektur) | P6, P7 |
Nicht ohne Freigabe: Verdrahtung in `bootstrap.py`, `RecoveryRunner` einhängen, neue Autonomie (Phase 14 Teilziel 5), MCP/OpenHands/pypdf, Three.js.

## 4. Empfehlung
Nach der Sammelabnahme zuerst P2–P5 (klein, additiv, ohne Freigaben, keine geschützten Pfade), parallel die Owner-Entscheidungen E5/E6/E7 und die Persistenzfrage (P6) einholen; erst danach P7–P9. Fokus bleibt ein stabiler, produktiv nutzbarer Windows-Assistent. In dieser Sitzung wurde **keine** V2-Funktion geändert: die offenen Änderungen gehören zu #186, und die V2-Pakete sind überwiegend freigabepflichtig.

## 5. Künftiges Sprachdesign V2 (Vorgabe des Owners 2026-11-15; Entwurf, nichts davon aktiviert oder umgesetzt)
* **Spracherkennung:** OpenAI (`gpt-transcribe`) als **bevorzugter** STT-Provider, **sobald** API-Schlüssel, Kostenlimit und Cloud-Audioübertragung **ausdrücklich** aktiviert sind (`voice.stt_cloud_enabled`; heute: Provider `auto` hängt die Cloud erst dann an die lokale Kette an, nicht davor). Bis dahin und bei jedem Ausfall: **lokales Whisper Base als Offline-Fallback** (bleibt Standard der Testkonfiguration; Medium als Qualitätsoption).
  Zu klären vor der Umsetzung (Owner): Reihenfolge der Kette („Cloud zuerst, dann lokal“ statt wie heute „lokal zuerst, dann Cloud“), Kostenlimit-Mechanismus (WP02a/E6 ist nicht durchgesetzt), Hinweis in NEXUS bei jeder Cloud-Erkennung, kein Audio speichern.
* **Eigene TTS-Stimme:** männlich, tief, ruhig, dezent britisch, natürliches Deutsch, futuristischer Klang im Stil eines modernen JARVIS 2026. Offen: Quelle der Stimme (lokales Modell vs. Cloud-Dienst), Lizenz, Latenz und RAM auf dem i5-9600KF mit 8 GB, Windows-Kompatibilität. **Die funktionierende Windows-TTS (Hedda, `tts_provider = "windows"`) wird nicht vorzeitig ersetzt**; eine neue Stimme kommt als zusätzlicher, wählbarer Provider hinter derselben `TTSProvider`-Schnittstelle (Registry-Muster wie bei STT), mit der heutigen Stimme als Rückfall.
* **Randbedingungen:** keine kostenpflichtigen API-Aufrufe ohne Freigabe, keine Smartphone- oder Cloud-Infrastruktur, PermissionEngine/Not-Aus unverändert (der Not-Aus muss auch eine neue TTS sofort stoppen, wie `WindowsTTS.stop`).
* **Zuordnung:** Arbeitspaket P1 (Sprache produktiv) in Abschnitt 3; Erweiterung um „TTS-Provider-Auswahl“ erst nach #186 und nach Owner-Entscheidung zur Stimmenquelle.
