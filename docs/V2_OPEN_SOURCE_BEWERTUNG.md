# JARVIS V2: Open-Source-First-Bewertung (Entwurf zur Freigabe)

**Status: Entwurf. Es wurde nichts installiert, kein fremder Code übernommen, keine Abhängigkeit eingetragen.** Dieses Dokument ist eine Vorprüfung; jede spätere Aufnahme braucht die formale Prüfdatei nach `docs/INTEGRATIONS.md` und eine ausdrückliche Besitzerfreigabe. Release-Freeze für Windows V1 bleibt bestehen. Stand der Recherche: 2026-11-11. Gehört zu `docs/V2_ARCHITEKTUR.md` und `docs/V2_BACKLOG.md`.

## 1. Methode, Maßstab und Grenzen der Recherche
**Maßstab** ist das verbindliche Prüfschema `docs/INTEGRATIONS.md`: AGPL/GPL ausgeschlossen; Telemetrie/Datenabfluss nur standardmäßig aus; keine bekannten, ungepatchten Schwachstellen; Windows-Kompatibilität belegt; Version plus Hash gepinnt; Verdrahtung nur in `bootstrap.py`; jede Aktion über `ToolRegistry` → `PermissionEngine`.

**Optionen je Agent/Säule:** **A** vorhandene JARVIS-Funktion weiterverwenden · **B** Open-Source-Projekt direkt integrieren (hinter unserer Kontrollstelle) · **C** Code/Konzepte gezielt übernehmen und anpassen · **D** selbst entwickeln.

**Zählweise:** „Abhängigkeiten“ = Einträge in `requires_dist` der PyPI-Metadaten inklusive optionaler Extras; „harte Abhängigkeiten“ = ohne Extras gezählt.

**Belegstufen** (jede Zelle nennt ihre Quelle): *PyPI* = öffentliche Registry-Metadaten (Version, Upload-Datum, `requires_python`, Abhängigkeiten, gemeldete Schwachstellen), *LICENSE* = die Lizenzdatei im Repository, direkt gelesen, *Doku/Bericht* = öffentliche Projektdokumentation oder Sicherheitsbericht (Link). Als Maß für „Pflege“ dient das **letzte PyPI-Upload-Datum**.

**Nicht geprüft (bewusst offen):** GitHub-Sterne und Commit-Aktivität (Aggregatoren widersprechen sich, die Atom-Feeds waren nicht erreichbar), tiefes Code-Review, tatsächliche Windows-Installation und -Läufe, Ressourcenverbrauch/API-Kosten im Betrieb, Hash-Listen der Abhängigkeiten. Nicht bewertet: Goose, Cline, Stagehand, STORM, Open Deep Research (nicht verifiziert, deshalb nicht als Kandidat geführt).

## 2. Vergleichsmatrix je V2-Säule
Spalten: Projekt (GitHub) · Lizenz · Reife/Pflege (PyPI) · Windows/Python · Vorteile · Nachteile/Risiken · Option.

### 2.1 Planung und Multi-Agenten-Orchestrierung
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT (LICENSE) | 1.2.20, 2026-11-05 | py≥3.10, 6 Abhängigkeiten | Zustandsautomat, Checkpointing, Mensch-in-der-Schleife | zweiter Orchestrator neben `AgentOrchestrator`; eigene Ausführungsschleife | **C** (Muster), nicht B |
| [CrewAI](https://github.com/crewAIInc/crewAI) | MIT (LICENSE) | 1.15.39, 2026-11-11 | py 3.10 bis 3.13, 59 Abhängigkeiten | große Verbreitung, Rollenmodell | Telemetrie standardmäßig an (Opt-out per Umgebungsvariable, [Doku](https://docs.crewai.com/telemetry)); eigene Agentenarchitektur | **nein** |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | MIT (LICENSE) | 1.25.0, 2026-11-07; 1.0 laut [Bericht](https://techstrong.ai/features/microsoft-ships-agent-framework-1-0-a-production-ready-foundation-for-multi-agent-ai/) im April 2026 | py≥3.11 | Nachfolger von AutoGen und Semantic Kernel | eigene Agentenarchitektur; Doppelung | **C** (Beobachten) |
| [AutoGen](https://github.com/microsoft/autogen) | Code MIT (PyPI), Repo-LICENSE CC-BY-4.0 für Doku | 0.7.5, 2025-09-30 | py≥3.10 | – | **Wartungsmodus** seit Oktober 2025, Nachfolger MAF ([Bericht](https://venturebeat.com/ai/microsoft-retires-autogen-and-debuts-agent-framework-to-unify-and-govern)) | **nein** |
| [Semantic Kernel](https://github.com/microsoft/semantic-kernel) | MIT (PyPI-Klassifizierer) | 1.47.0, 2026-11-05 | py≥3.11 | – | laut [Bericht](https://venturebeat.com/ai/microsoft-retires-autogen-and-debuts-agent-framework-to-unify-and-govern) zusammen mit AutoGen im Wartungsmodus | **nein** |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | MIT (PyPI) | 0.24.0, 2026-10-15 | py≥3.10, 56 Abhängigkeiten | typisierte Übergaben (Handoffs) | Vor-1.0-Version; Standard-Tracing/Datenabfluss nicht geprüft | **C** (Muster) |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | MIT (PyPI) | 2.67.0, 2026-11-11 | py≥3.11, 31 Abhängigkeiten | strenge Typisierung der Ausgaben | zweite Agentenschleife | **C** (Muster) |
| [smolagents](https://github.com/huggingface/smolagents) | Apache-2.0 (LICENSE) | 1.26.0, 2026-05-29 | py≥3.10, 53 Abhängigkeiten | schlank | der Agent schreibt und führt Python-Code aus; lokaler Executor mit Sandbox-Ausbruch ([JFrog, CVE-2025-9959](https://research.jfrog.com/vulnerabilities/smolagents-local-python-sandbox-escape-jfsa-2025-001434277/), bis 1.21.0; Fix in der aktuellen Version nicht verifiziert) | **nein** |

**Befund:** `AgentOrchestrator`, `GoalEngine`, `AgentRouter`, Recovery und Journal (zusammen rund 5000 Zeilen, dicht getestet) leisten bereits Abhängigkeiten, Prioritäten, Nebenläufigkeit, Abbruch, Zeitlimits und begrenzte Wiederholung unter der PermissionEngine. Jedes Framework brächte eine **zweite Ausführungsschleife** mit eigenem Berechtigungsmodell. **Empfehlung: Option A** (behalten); aus LangGraph (Checkpointing) und dem Agents SDK (typisierte Übergaben) nur **Muster** übernehmen (V2-06).

### 2.2 Coding, Test- und Reparaturzyklen
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [OpenHands](https://github.com/OpenHands/OpenHands) + [Software Agent SDK](https://github.com/OpenHands/software-agent-sdk) | MIT (beide LICENSE) | SDK 1.61.0, 2026-11-09; App 1.11.0, 2026-07-09 | **py≥3.12** (SDK) bzw. 3.12 bis 3.13 (App); Windows laut [Doku](https://docs.openhands.dev/openhands/usage/run-openhands/local-setup) über WSL + Docker Desktop; „Local Runtime“ ohne Sandbox, auf Windows nur CLI/Headless, Browser-Werkzeug dort nicht unterstützt | ausgereifter Coding-Agent (Planen, Editieren, Testen, Git), Sandbox-Betrieb in Docker | schwer (App 85 Abhängigkeiten); eigener Berechtigungsrahmen; braucht Docker/WSL; Python höher als unser Minimum | **B** (isolierter Worker, bedingt) |
| [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | MIT (LICENSE) | 2.4.6, 2026-07-23 | py≥3.10, „OS independent“; 14 harte Abhängigkeiten (u. a. `litellm`, `datasets`, `textual`) | sehr kleiner Agentenkern, einfach auditierbar | führt Shell-Befehle aus; viele Abhängigkeiten für einen „kleinen“ Agenten | **C/B** (Alternative zu OpenHands) |
| [Aider](https://github.com/Aider-AI/aider) | Apache-2.0 (LICENSE) | 0.86.2, 2026-02-12 | **py 3.10 bis 3.12**, 301 Abhängigkeiten | bewährter Pair-Programming-Workflow | **zwei ungepatchte CVEs** in der aktuellen Version ([CVE-2026-10177](https://nvd.nist.gov/vuln/detail/CVE-2026-10177), CVE-2026-10175; PyPI führt vier Einträge, kein Fix) | **nein** (Regel „ungepatcht“) |
| [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) | `main`: Apache-2.0 (LICENSE); PyPI-Paket 0.4.3 (2024-10-26) stammt aus der älteren Linie, Lizenz dort nicht geprüft | PyPI veraltet | – | – | führt generierten Code laut Projektbeschreibung lokal aus; Sandbox-Eigenschaften nicht geprüft | **nein** (Vorsicht, nicht belegt) |
| unser `coding/` + `self_repair/` + `self_improvement/` | eigener Code | vorhanden | Windows-Prozessbaum (`winjob`, bisher in `self_improvement/`), CI | durchgängig unter PermissionEngine, Freigabe durch den Menschen | echte LLM-Vorschläge ungetestet; keine PR-Schleife | **A** + gezielte B |

### 2.3 Recherche und Quellenbewertung
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | **widersprüchlich**: LICENSE Apache-2.0, PyPI „MIT“ (beide permissiv, aber zu klären) | 0.17.0, 2026-11-09 | **py≥3.12**, 165 Abhängigkeiten | fertige Mehrquellen-Recherche mit Bericht | würde als eigene Pipeline neben unseren Browser-Freigaben laufen; LLM-Kosten nicht gemessen; schwere Abhängigkeitslast | **C** (Konzepte) |
| unser `research/` (+ V2-01 Quellenbewertung) | eigener Code | vorhanden, Echt-Browser-CI | Windows-CI grün | jede Seite über Browser-Tool + Freigabe, Quellen und Widersprüche sichtbar | Suchtext regelbasiert, kein Zitatabgleich | **A** + **D** (klein) |

### 2.4 Browser
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [browser-use](https://github.com/browser-use/browser-use) | MIT (LICENSE) | 1.0.2, 2026-11-11 | py≥3.11, 10 Abhängigkeiten | schlank, aktiv, DOM-Aufbereitung für Modelle | eigene Agentenschleife steuert den Browser direkt (**umgeht** `BrowserController`/PermissionEngine); **Telemetrie standardmäßig an** (PostHog, Opt-out [Doku](https://docs.browser-use.com/open-source/development/monitoring/telemetry)); früherer `allowed_domains`-Umgehungsfehler ([CVE-2025-47241](https://www.miggo.io/vulnerability-database/cve/CVE-2025-47241), Version 0.1.45) | **C** (DOM-Aufbereitung, nach Review) |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Apache-2.0 (LICENSE) | Betrieb/Version nicht im Detail geprüft | – | Browser als MCP-Werkzeug | Betriebsart (Node/npm) und Rechte nicht geprüft | **B über das Gateway** (nach 3.1, später) |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | **AGPL-3.0** (LICENSE) | 1.0.57, 2026-11-06 | py 3.11 bis 3.14 | – | Lizenzausschluss | **nein** |
| unser `browser/` | eigener Code (2223 Z.) | vorhanden | Echt-Browser-CI Windows/Linux | Regeln: keine Logins, keine internen Adressen, keine ausführbaren Downloads | – | **A** |

### 2.5 Dateien, Office, Dokumente
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause (PyPI, LICENSE) | 7.0.1, 2026-11-10; 0 gemeldete Schwachstellen | py≥3.10, „OS independent“, **1 harte Abhängigkeit** (`typing_extensions`), reines Python | klein, auditierbar, PDF-Text lesen | kein OCR, Layout begrenzt | **B** (Bibliothek) |
| [MarkItDown](https://github.com/microsoft/markitdown) | MIT (LICENSE) | 0.1.9, 2026-10-21 | py 3.10 bis 3.14; 7 harte Abhängigkeiten + Extras (`pdf`, `docx`, `pptx`, `xlsx` …) | viele Formate nach Markdown | der MCP-Server nimmt URIs/`file://` an (SSRF/Dateizugriff), Microsoft: „as designed“, nur Doku-Hinweis ([OX Security](https://www.ox.security/research-news/markitdown-mcp-exposes-developer-machines-to-file-theft/), Sekundärquelle); Magika (native Teile) | **B** später, nur mit Dateipfaden (nie URIs) |
| [Docling](https://github.com/docling-project/docling) | MIT (PyPI) | 2.150.0, 2026-11-10 | py 3.10 bis <4 | Layout-/Tabellenerkennung | ML-Modelle, Ressourcenbedarf nicht geprüft | **beobachten** |
| [PyMuPDF](https://github.com/pymupdf/pymupdf) | **AGPL-3.0 oder kommerziell** (PyPI) | 2.1, 2026-11-02 | – | – | Lizenzausschluss | **nein** |
| unser `files/`, `office/`, `FilesAgent`; `python-docx`, `openpyxl`, `defusedxml` | bereits geprüft (`docs/integrations/`) | vorhanden | Windows-CI | anlegen/lesen mit Freigaben | PDF fehlt, bestehende Office-Dateien nur lesen | **A** |

### 2.6 Windows-Computersteuerung
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [UFO² / UFO³](https://github.com/microsoft/UFO) | MIT (LICENSE) | v3.0.0 im November 2025 laut einem Mirror der Release-Seite ([github.gg22.workers.dev](https://github.gg22.workers.dev/microsoft/UFO/releases), Drittdomain, nicht direkt verifiziert); UFO² laut diesem Mirror weiter unterstützt | Windows-Agent mit UIA + Sicht ([Doku](https://microsoft.github.io/UFO/ufo2/overview)); unter dem Namen `ufo-agent` **kein PyPI-Paket** gefunden (Installation laut Projekt aus dem Repository, nicht geprüft) | beste Konzeptvorlage: UIA zuerst, Sicht als Rückfall, App-Spezialisten | schwere eigene Schleife; Installation aus Repo-Quellen, nicht pinbar per Hash wie PyPI | **C** (Konzepte) |
| [Agent S](https://github.com/simular-ai/Agent-S) | Apache-2.0 (LICENSE) | `gui-agents` 0.3.2, 2025-12-16 | **py ≤ 3.12**; braucht ein Grounding-Modell ([README](https://pypi.org/project/gui-agents)) | Forschungsstand | Forschungscode, führt Python-Code zur Steuerung aus; Einzelmonitor | **nein** |
| [Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | MIT (LICENSE) | 0.8.8, 2026-10-10; 20 Abhängigkeiten | **py≥3.14 laut PyPI**; UIA + PyAutoGUI | schneller Weg zu einem MCP-Desktop-Werkzeug | sehr breite Rechte (gesamter Desktop), keine Sicherheitsprüfung gefunden; läuft nur in einem eigenen Python 3.14-Prozess | **B über das Gateway** (nur mit Allowlist, später) |
| [OmniParser](https://github.com/microsoft/OmniParser) | Repo-LICENSE: CC-BY-4.0; Modelle uneinheitlich (älteres `icon_detect` AGPL, Beschreiber MIT, neues Modell laut README MIT-basiert, nicht verifiziert) | – | GPU-lastig | Bildschirm-Parsing | Lizenzlage unklar | **nein** (derzeit) |
| unser `computer/` (4201 Z., 475 Tests), `ui`-Tool, UIA-Aktionen | eigener Code | vorhanden | Windows-CI (Notepad-E2E) | jede Eingabe einzeln freigegeben, Notaus | keine wiederverwendbaren Abläufe | **A** + **D** (Skills, V2-13) |

### 2.7 Langzeitgedächtnis
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 (LICENSE) | 2.2.1, 2026-09-25 | py≥3.10, 56 Abhängigkeiten | fertige Gedächtnisschicht | **Telemetrie standardmäßig an** (PostHog; Umgebungsvariable muss vor dem Import gesetzt sein, [Bericht](https://instagit.com/mem0ai/mem0/how-does-mem0-handle-telemetry-and-data-collection-and-can-it-be-disabled)); zweite Datenhaltung neben `memory/`; Backend-Anforderungen nicht geprüft | **nein** (jetzt) |
| [Letta](https://github.com/letta-ai/letta) | Apache-2.0 (LICENSE) | PyPI-Paket `letta` ist laut Beschreibung „Letta Code“, Paketlage unklar | – | – | eigener Agentenserver | **nein** |
| [Graphiti](https://github.com/getzep/graphiti) | Apache-2.0 (PyPI) | 0.31.2, 2026-10-20 | py≥3.10 | zeitlicher Wissensgraph | Datenbank-Anforderung nicht geprüft | **beobachten** |
| [cognee](https://github.com/topoteretes/cognee) | Apache-2.0 (PyPI) | 1.6.7, 2026-11-06 | 141 Abhängigkeiten | – | sehr schwer | **nein** |
| unser `memory/` | eigener Code | vorhanden | SQLite, lokale TF-IDF-Suche, `SecretGuard` | lokal, geschwärzt, Windows-CI | keine Namensräume/Verdichtung | **A** + **D** (V2-07) |

### 2.8 Agentenüberwachung / Beobachtbarkeit
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) | Apache-2.0 (PyPI) | SDK 1.45.2, 2026-10-29; 4 Abhängigkeiten | py≥3.10 | Standard für Spuren | ohne Backend wenig Nutzen; Doppelung zu Audit/Verlauf | **beobachten** |
| [Langfuse](https://github.com/langfuse/langfuse) | MIT außer `ee/`-Verzeichnissen (LICENSE) | SDK 5.2.0, 2026-11-05 | py≥3.11 | LLM-Spuren | Server als Zusatzdienst (Betrieb nicht geprüft) | **nein** (jetzt) |
| [Phoenix](https://github.com/Arize-ai/phoenix) | **Elastic-2.0** (PyPI), keine permissive Lizenz | 21.0.0 | – | – | Lizenzausschluss | **nein** |
| unser Audit, `history/`, `/view/audit`, `/view/history` | eigener Code | vorhanden | Windows-CI | geschwärzt, lesend | keine Agenten-Zeitleiste | **A** + **D** (V2-12) |

### 2.9 Querschnitt: Protokoll für externe Werkzeuge
| Projekt | Lizenz | Reife / Pflege | Windows / Python | Vorteile | Nachteile / Risiken | Option |
|---|---|---|---|---|---|---|
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT (LICENSE) | 2.3.0, 2026-10-02; 0 gemeldete Schwachstellen | py≥3.10; 16 harte Abhängigkeiten (u. a. `starlette`, `pyjwt[crypto]`, `pywin32`, `opentelemetry-api`) | ein Standardprotokoll für viele externe Werkzeuge (Browser, Desktop, Dokumente …) | Werkzeugbeschreibungen können Anweisungen enthalten (**Tool Poisoning**), „Confused Deputy“ ([CSA-Studie](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-agentic-attack-surface-20260516/), [Microsoft](https://techcommunity.microsoft.com/blog/microsoft-security-blog/the-state-of-mcp-security-in-2026/4531327)); Abhängigkeitslast des Clients | **B** (als Gateway, siehe 4) |

## 3. Ausgeschlossen nach unseren Regeln
| Projekt | Grund |
|---|---|
| Skyvern, PyMuPDF | AGPL (Regel „Lizenz“) |
| Phoenix | Elastic License 2.0, nicht permissiv |
| Aider | ungepatchte Schwachstellen in der aktuellen Version, Python < 3.13 |
| smolagents | Agent führt generierten Code lokal aus, bekannter Sandbox-Ausbruch |
| Open Interpreter | lokale Code-Ausführung (Sandbox nicht geprüft); PyPI-Stand veraltet |
| AutoGen, Semantic Kernel | Wartungsmodus (Nachfolger MAF) |
| CrewAI, Mem0, browser-use (als Ganzes) | Telemetrie standardmäßig an, zweite Agenten-/Datenarchitektur |
| Agent S, OmniParser | Forschungscode beziehungsweise unklare Lizenzlage |

## 4. Entscheidung je Säule
| Säule | Empfehlung | Begründung |
|---|---|---|
| 1 Planung / 2 Multi-Agent | **A**, **C** (Muster aus LangGraph, Agents SDK) | vollständig vorhanden; ein Framework wäre eine zweite Architektur |
| 3 Coding | **B** isolierter Worker (OpenHands), sonst **A** | größter Funktionsgewinn; nur hinter Sandbox und Freigabe |
| 4 Recherche | **A** + **D** (V2-01, V2-10) | Eigenentwicklung klein; fremde Frameworks umgehen Browser-Freigaben |
| 5 Dateien / Office | **A** + **B** (pypdf) | PDF lesen ohne Eigenbau |
| 6 Computersteuerung | **A**, **C** (UFO²-Konzepte), **B** nur über das Gateway | Bestand dicht getestet; fremde Desktop-Agenten haben zu breite Rechte |
| 7 Gedächtnis | **A** + **D** | Mem0 und Co. verletzen Telemetrie-/Datenregel oder brauchen Zusatzdienste |
| 8 Überwachung | **A** + **D** (lesende Sichten) | keine Zusatzdienste |

## 5. Bewertungsraster der aussichtsreichsten Kandidaten
Einschätzung 1 (schlecht) bis 5 (gut); subjektiv, aus den Belegen in Abschnitt 2 abgeleitet.

| Kandidat | Funktion | Reife | Lizenz / Regeln | Windows | Kontrollierbarkeit | Aufwand | Wartbarkeit | Summe |
|---|---|---|---|---|---|---|---|---|
| MCP SDK als Gateway (B) | 5 | 4 | 5 | 4 | 4 | 3 | 4 | **29** |
| pypdf (B) | 3 | 5 | 5 | 5 | 5 | 5 | 5 | **33** |
| OpenHands als Worker (B) | 5 | 4 | 5 | 2 | 3 | 2 | 3 | **24** |
| MarkItDown (B) | 4 | 3 | 4 | 4 | 3 | 4 | 4 | **26** |
| browser-use (C) | 4 | 4 | 3 | 4 | 2 | 3 | 3 | **23** |
| UFO² (C, Konzepte) | 4 | 3 | 5 | 4 | 3 | 3 | 3 | **25** |
| LangGraph (C, Muster) | 4 | 5 | 5 | 4 | 2 | 2 | 4 | **26** |

## 6. Die besten drei Integrationskandidaten
Die Reihenfolge richtet sich nach der **Hebelwirkung** unter Einhaltung aller Regeln, nicht nach der Rastersumme: pypdf hat die höchste Summe, ist aber ein kleiner Baustein; das Gateway öffnet den Zugang zu vielen Werkzeugen, und OpenHands schließt die größte Funktionslücke.

1. **MCP-Gateway auf Basis des offiziellen MCP Python SDK (Option B).** Ein einziger, kontrollierter Zugang für viele externe Werkzeuge und Agenten (Playwright MCP, Windows-MCP, Dokumentenwerkzeuge …). Damit entsteht der Funktionsgewinn **ohne** zweite Agentenarchitektur. Vorarbeit liegt als Backlogschritt `mcp-security-review` vor (Besitzer-Freigabe nötig).
2. **OpenHands als isolierter Coding-Worker (Option B, bedingt).** Funktional der stärkste offene Coding-Agent. Bedingungen: Sandbox-Entscheidung (`docs/SANDBOX_DESIGN.md`), Docker/WSL-Betrieb, Python ≥ 3.12 nur im Worker-Container, Ergebnis ausschließlich als Diff zur menschlichen Freigabe. Leichtere Alternative: mini-swe-agent.
3. **pypdf für PDF-Lesen im Datei-/Office-Agent (Option B, Bibliothek).** Kleinste Abhängigkeit (1 harte), BSD-3, reines Python, sofort nutzbar. MarkItDown später als Erweiterung, nur mit Dateipfaden.

**Beobachten, nicht integrieren:** Microsoft Agent Framework, UFO² (Konzepte für V2-13), LangGraph (Checkpoint-Muster für V2-06), Docling, Graphiti, OpenTelemetry.

## 7. Integrationsarchitektur: „External Agent Gateway“ (Entwurf)
Ziel: Externe Agenten und Werkzeuge nutzen, **ohne** unsere Kontrollstelle zu umgehen und **ohne** zweite Agentenarchitektur.

```
JARVIS-Agent (bestehender Adapter-Typ)  ──►  ToolGateway  ──►  ToolRegistry  ──►  PermissionEngine ► Not-Aus ► Audit
                                                                       │
                                                         ExternalToolAdapter (ProtectedTool je externem Werkzeug)
                                                                       │ stdio, lokale Kindprozesse, kein Netz-Listener
                                                         MCP-Gateway (SDK-Client) ─► externer Server / Worker (eigener Prozess, eigener venv oder Container)
```
**Wiederverwendet:** `Agent`-Schnittstelle (`agents/agent.py`), `AgentRegistry`, `ToolGateway`, `ToolRegistry`, `PermissionEngine`, Audit, Windows-Prozessbaum (`self_improvement/winjob.py`), Journal. **Neu:** nur der Adapter und das Gateway (V2-14, Entwurf).

**Verbindliche Regeln:**
1. **Jeder externe Aufruf ist ein Werkzeugaufruf** über `ToolRegistry.execute`; jedes externe Werkzeug wird als `ProtectedTool` mit Grundregel **YELLOW** (Einzelbestätigung) registriert. Externe Agenten erhalten **keine** eigenen Berechtigungen und sehen keine Berechtigungsentscheidung.
2. **Allowlist vom Besitzer:** nur ausdrücklich konfigurierte Server, feste Version und Hash (`--require-hashes`), fester Startbefehl; kein Auto-Update, keine Installationsskripte, kein `npx`/`curl | sh` zur Laufzeit.
3. **Tool-Poisoning-Schutz:** Werkzeugname, Schema und Beschreibung werden beim ersten Prüflauf **gehasht und gepinnt**; Abweichung → Werkzeug gesperrt. Beschreibungen gehen nicht ungeprüft an ein Modell. Ergebnisse sind **Daten**, nie Anweisungen; sie werden begrenzt, geschwärzt und gekennzeichnet.
4. **Isolierung:** eigener Prozess (Windows: Job Object (vorhandener Baustein `self_improvement/winjob.py`, wie beim Coding-Anbieter nur über `bootstrap.py` eingebunden) mit Zeit-/Speicherlimit), Arbeitsverzeichnis = bestätigte Kopie, minimale Umgebung (keine Schlüssel, keine Elternumgebung), nur stdio, kein Server-Port. Netzwerkzugriff des Kindprozesses: Standard aus; **die Durchsetzung unter Windows ist ungelöst** (Blocker, siehe 8).
5. **Fähigkeiten minimal:** keine Rückkanäle des Servers an unser Modell (kein Sampling, kein Elicitation, keine Roots-Freigabe), keine Server-initiierten Dateizugriffe.
6. **Not-Aus und Abbruch:** Not-Aus beendet alle Kindprozesse sofort (Prozessbaum); Orchestrator-Abbruch/Zeitlimit wirkt wie bei jedem Agenten; Wiederholungen nach den bestehenden Obergrenzen.
7. **Standard aus**, Verdrahtung nur in `bootstrap.py`, Tests gegen unser Prüfschema (`tests/test_integration_docs.py`); **neue Fähigkeiten** (`KNOWN_CAPABILITIES`) nur mit ausdrücklich ausgewiesener Testanpassung.
8. **Keine Telemetrie:** Server mit Standard-Telemetrie nur, wenn sie per Umgebung nachweislich abgeschaltet ist (Test).

**CI-Tests ohne Fremdcode:** ein **Fake-MCP-Server** (reines Python, JSON-RPC über stdio) in `tests/` simuliert gutartige und feindliche Server: vergiftete Beschreibung, geänderte Schema-Hash, übergroße Ausgabe, Hänger, Absturz, Ausgabe mit eingeschleusten Anweisungen, Rückkanal-Versuche. Dazu Windows-Runner-Tests für Prozessbaum-Ende und Not-Aus. Erst danach kann ein echter Server (Playwright MCP, Windows-MCP) in einem eigenen, freigegebenen Schritt geprüft werden.

## 8. Offene Punkte und Blocker
1. **Netzwerkisolation unter Windows** für Kindprozesse ist nicht gelöst (kein Container im Standard); ohne sie bleiben nur Allowlist, minimale Umgebung und Freigaben. Eine Entscheidung zu `docs/SANDBOX_DESIGN.md` ist nötig.
2. **Abhängigkeitslast des MCP-SDK-Clients** (16 harte Abhängigkeiten); Alternative D: schlanker eigener stdio-Client (rund 300 Zeilen) mit höherem Wartungs- und Konformitätsaufwand. Entscheidung in der Prüfdatei `docs/integrations/mcp.md`.
3. **OpenHands:** Docker Desktop/WSL als Voraussetzung, Python ≥ 3.12 nur im Worker; Betrieb unter Windows ist nicht von uns geprüft.
4. **Nicht belegt:** GitHub-Aktivität, tatsächlicher Ressourcen- und API-Kostenverbrauch, Fix-Stand von smolagents, Lizenzen einzelner Modellgewichte (OmniParser).
5. Lizenzangabe bei GPT Researcher widersprüchlich (PyPI MIT, LICENSE Apache-2.0); vor jeder Nutzung klären.

## 9. Freigabefragen an den Besitzer
1. Soll das **MCP-Gateway** (Top 1) als V2-14 mit zuerst `docs/MCP_SECURITY.md` und `docs/integrations/mcp.md` vorbereitet werden (nur Dokumente, kein Code)?
2. Soll die **Sandbox-Entscheidung** für den OpenHands-Worker (Top 2) getroffen werden, oder bleibt Coding bei Option A?
3. Soll **pypdf** (Top 3) per Prüfdatei `docs/integrations/pypdf.md` und danach per Erweiterung von `files`/`office` (Lesen) vorbereitet werden?
4. Bleibt es bei **keiner** Übernahme fremden Codes (Option C nur als Konzept), bis jeweils eine Lizenz- und Sicherheitsprüfung vorliegt?

## 10. Quellen
Registry-Metadaten: `https://pypi.org/pypi/<paket>/json` (Stand 2026-11-11). Lizenzdateien: `raw.githubusercontent.com/<projekt>/…/LICENSE`. Berichte und Dokumentation: [AutoGen/MAF](https://venturebeat.com/ai/microsoft-retires-autogen-and-debuts-agent-framework-to-unify-and-govern), [OpenHands lokal](https://docs.openhands.dev/openhands/usage/run-openhands/local-setup), [Browser-Use Telemetrie](https://docs.browser-use.com/open-source/development/monitoring/telemetry), [CVE-2025-47241](https://www.miggo.io/vulnerability-database/cve/CVE-2025-47241), [CVE-2026-10177](https://nvd.nist.gov/vuln/detail/CVE-2026-10177), [CrewAI Telemetrie](https://docs.crewai.com/telemetry), [smolagents/JFrog](https://research.jfrog.com/vulnerabilities/smolagents-local-python-sandbox-escape-jfsa-2025-001434277/), [UFO²](https://microsoft.github.io/UFO/ufo2/overview), [MarkItDown/OX](https://www.ox.security/research-news/markitdown-mcp-exposes-developer-machines-to-file-theft/), [MCP-Sicherheit CSA](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-agentic-attack-surface-20260516/), [MCP-Sicherheit Microsoft](https://techcommunity.microsoft.com/blog/microsoft-security-blog/the-state-of-mcp-security-in-2026/4531327), [Mem0 Telemetrie](https://instagit.com/mem0ai/mem0/how-does-mem0-handle-telemetry-and-data-collection-and-can-it-be-disabled). Sekundärquellen sind als solche gekennzeichnet.
