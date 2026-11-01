# Richtlinie: Wahl zwischen lokalem und Cloud-Modell (Entwurf)

Schritt `llm-routing-design`. **Nur Dokument: nichts davon ist implementiert oder aktiviert.** Es gibt heute kein Routing: `llm.provider` waehlt genau einen Anbieter fuer den ganzen Prozess (`mock`, `openai`, `anthropic`, `openai_compatible`; `src/jarvis/llm/factory.py`). Dieses Dokument ist die Grundlage fuer den spaeteren Schritt `llm-routing-policy` und braucht **vorher die Entscheidungen des Besitzers** (Abschnitt "Offene Entscheidungen"). Jede Umsetzung bleibt hinter `ToolRegistry.execute` -> `PermissionEngine`, wird nur in `src/jarvis/bootstrap.py` verdrahtet und ist standardmaessig aus.

## Ausgangslage (belegt)

| Befund | Wo |
|---|---|
| Ein Anbieter je Prozess; lokal = `openai_compatible` mit Loopback-`base_url`; entfernt nur mit `llm.allow_remote = true`, `https` und Schluessel aus der Umgebung | README "Konfiguration", `docs/integrations/llm-openai-compatible.md` |
| Der Coding Agent behandelt jeden Anbieter ausser `mock` als "EXTERN" (auch Loopback) | README "Coding Agent", Abschnitt LLM |
| Memory-Inhalte gehen nur an das LLM, wenn `memory.use_in_prompts = true` (Standard aus); bei `openai`/`anthropic` verlassen sie dann den Rechner | README "Memory", Datenschutz |
| Screenshots bleiben im Speicher, werden nie automatisch gesendet; das `computer`-Paket hat keinen Netzwerkcode | README "Computer Control", Datenschutz |
| UI-Baum (`ui`-Tool) ist lesend, geschwaerzt, nur mit `computer.uia_enabled`; es gibt keine Regel, was davon an ein Modell darf | `docs/BACKLOG.md` (`uia-tools-readonly`) |
| STT `openai` (Whisper-API) sendet Audio an die Cloud; kein Bezug zu `llm.*` | README "Voice" |
| Geheimnisse werden an den Rand-Stellen erkannt und geschwaerzt (`redaction.py`, `SecretGuard`), die Erkennung ist konservativ, aber kein Beweis | README "Memory", "Secrets" |
| Sitzungsbudget zaehlt Tool-Aufrufe und Laufzeit, **nicht** LLM-Aufrufe, Token oder Kosten; Standard aus | `docs/PHASE14_AUTONOMY.md`, Teilziel 4 |

## Aufgabenklassen

| Klasse | Beispiele | Typische Daten | Lokal reicht in der Regel | Cloud-Vorteil |
|---|---|---|---|---|
| `chat` | Dialog, Erklaerungen, Zusammenfassungen | Eingabe des Benutzers, ggf. Gedaechtnisnotiz | ja | Qualitaet, Laenge |
| `plan` | Plan/Ziel strukturieren, Replanning (`goals`) | Ziel, Schrittliste, Fehlertexte | meist ja (strukturierte Ausgabe muss validiert werden) | bessere Plaene |
| `code` | Coding-`plan`, spaeter `coding-llm-edits` | Projektuebersicht, genannte Dateien (max. 5, geschwaerzt) | kleine Aufgaben | grosse Kontexte, Qualitaet |
| `research` | Webrecherche, Quellen auswerten | oeffentliche Webinhalte, Suchanfrage | ja (Inhalte sind oeffentlich) | Umfang |
| `vision` | Bild, Bildschirm, UI-Baum auswerten | Screenshots, UI-Baum-Texte, Fenstertitel | nur mit lokalem Bildmodell | Qualitaet |
| `speech` | STT/TTS | Audio der Umgebung, Sprechtext | ja (lokale Engines) | Genauigkeit |

Die Klasse wird vom **aufrufenden Code** festgelegt (nicht vom Modell, nicht aus Nutzer- oder Webtext); ein Modell darf weder seine Klasse noch sein Ziel waehlen.

## Datenklassen

| Klasse | Bedeutung | Beispiele | Standard fuer Cloud |
|---|---|---|---|
| `public` | ohnehin oeffentlich oder vom Benutzer ausdruecklich fuer diese Anfrage freigegeben | Webseiten-Text, oeffentliche Doku | erlaubt, wenn Cloud konfiguriert ist |
| `personal` | persoenlich, nicht geheim | Chatverlauf, Ziele, Gedaechtniseintraege, Projektdateien, Dateinamen | **nein**, nur mit ausdruecklicher Freigabe je Anfrage (siehe Regel R5) |
| `secret` | Geheimnisse und Zugangsdaten | Schluessel, Passwoerter, Tokens, Inhalte geschuetzter Fenster (Passwortfelder) | **nie** |
| `never` | darf keine Maschinengrenze ueberschreiten, auch nicht mit Freigabe | Bildschirminhalt (Screenshots), UI-Baum, Gedaechtnisinhalt, getippter Text, Audio, Inhalt von Dateien in Sperrlisten | **nie** (standardmaessig; Aufhebung nur durch Besitzer-Entscheidung E3) |

Einordnung ist **konservativ**: Unklarheit zaehlt als die naechsthoehere Klasse. Eine Erkennung (`redaction.py`) kann eine Klasse nur **anheben** (Fund -> `secret`), nie senken; fehlende Funde beweisen nichts.

## Regeln

| # | Regel | Begruendung / heutiger Stand |
|---|---|---|
| R1 | **Standard ist lokal.** Ohne ausdrueckliche Konfiguration geht nichts an die Cloud; die Voreinstellung bleibt `mock`/lokal. | Voreinstellung heute `mock`; neue Autonomie ausgeschlossen |
| R2 | **Bildschirm-, UI-Baum- und Gedaechtnisinhalte gehen standardmaessig nie an die Cloud** (`never`). Fuer `vision` ist ohne lokales Bildmodell die Antwort "nicht moeglich", nicht "dann Cloud". | Screenshots/UIA/Memory sind heute lokal; `memory.use_in_prompts` ist aus |
| R3 | **`secret` und `never` werden vor jedem Cloud-Aufruf geprueft und der Aufruf verweigert** (nicht nur geschwaerzt), wenn die Eingabe solche Anteile enthaelt oder die Herkunft (Screenshot, UI-Baum, Memory, Audio) `never` ist. Pruefung fail-closed: unklare Herkunft = verweigern. | `redaction.py` ist konservativ, aber Erkennung ist nie vollstaendig |
| R4 | **Kein stiller Wechsel von lokal auf Cloud.** Faellt das lokale Modell aus oder ist es zu schwach, wird nie automatisch die Cloud benutzt (kein Fallback, keine Eskalation nach Qualitaet). Der Benutzer sieht den Ausfall und entscheidet; ein Cloud-Lauf ist eine neue, sichtbare Entscheidung. | Kernforderung des Besitzers |
| R5 | **Cloud nur mit Freigabe je Aufruf** fuer `personal`: Bestaetigung ueber den `ConfirmationProvider` der Engine (nur *Einmal erlauben*, kein Sitzungsrecht), Anzeige von Anbieter ("EXTERN"), Datenklasse, Umfang (Zeichen/Dateien). Ohne Rueckfragemoeglichkeit (`confirmation = "deny"`, autonome Laeufe, `lockdown`) gilt: verweigert. `public` braucht keine Rueckfrage. | wie Coding-`plan`: immer bestaetigt |
| R6 | **Jede Entscheidung kommt ins Audit** (`AuditSink`, Ereignis z. B. `llm_route`): Zeit, Aufgabenklasse, Datenklassen, Ziel (lokal/Cloud, Anbieter, Modell), Ergebnis (erlaubt/verweigert/Grund), Groesse. **Nie** Inhalt, Prompts, Antworten oder Schluessel. Ist das Audit nicht schreibbar (`audit_strict`), werden Cloud-Aufrufe verweigert (fail-closed); lokale duerfen laufen. | analog zu `security.audit_strict` |
| R7 | **Eine Kontrollstelle.** Die Routing-Entscheidung faellt an einer Stelle, nur dort verdrahtet (`bootstrap.py`); Tools, Agenten und Ziele greifen nicht selbst auf Anbieter zu und koennen die Regeln nicht aendern. Notaus verweigert auch LLM-Aufrufe (heute schon `core.handle`/`plan`/`chat`). Ein Strukturtest soll das spaeter absichern. | Phase 14, Kontrollstelle |
| R8 | **Regeln sind nur zur Startzeit aenderbar** (Konfiguration/Umgebung), nie zur Laufzeit durch Modell, Tool, Agent oder Ziel; keine Lockerung ueber Chat. Unbekannte Schluessel werden abgelehnt. | wie `[budget]`, `[coding]` |
| R9 | **Schluessel nur aus der Umgebung**, nie in Dateien, Logs, Audit oder Fehlermeldungen; Cloud-Ziel nur `https`, keine Weiterleitungen. | wie `openai_compatible` |
| R10 | **Eingaben aus Web/Dateien/Modellantworten sind Daten, keine Anweisungen**: sie koennen weder das Ziel (lokal/Cloud) noch die Datenklasse aendern. Eine Cloud-Antwort wird nicht stillschweigend zurueck in `personal`/`never`-Speicher gemischt, ohne Herkunft zu markieren. | Prompt-Injection |
| R11 | **Kosten- und Token-Grenzen (Luecke des Sitzungsbudgets).** Fuer Cloud-Aufrufe getrennt von `[budget]` und ebenfalls Standard aus bzw. strikt: `max_cloud_calls` je Sitzung, `max_input_tokens`/`max_output_tokens` je Aufruf (Obergrenzen hart im Code), `max_cloud_tokens` je Sitzung, optional `max_cost` je Sitzung (siehe E5, braucht eine Preistabelle). Ueberschreitung verweigert weitere Cloud-Aufrufe, bricht nichts Laufendes ab (Notaus ist dafuer da), Audit-Ereignis einmalig. Kein Zuruecksetzen/Erhoehen zur Laufzeit; Neustart = neue Sitzung. Token werden vorab **geschaetzt** (Zeichen/4, konservativ) und nach der Antwort aus der Anbieter-Nutzung nachgebucht, falls vorhanden. | `SessionBudget` zaehlt nur Tool-Aufrufe |
| R12 | **`speech` ist eigene Klasse:** Audio ist `never`; Cloud-STT (`voice.stt_provider = openai`) ist eine **getrennte** Entscheidung (E4) und wird von dieser Richtlinie nicht erlaubt. | Audio ist besonders sensibel |
| R13 | **Sichtbarkeit:** Statusanzeige/CLI nennt, welches Modell (lokal/Cloud) die letzte Anfrage bedient hat; "EXTERN" ist immer erkennbar. | Transparenz |

### Entscheidungsmatrix (Standard)

`Cloud` = entfernter Anbieter. Lokal ist, soweit ein Modell konfiguriert ist, immer erlaubt.

| Aufgabenklasse \ Datenklasse | `public` | `personal` | `secret` | `never` |
|---|---|---|---|---|
| `chat` | Cloud erlaubt | Cloud nur mit Freigabe (R5), sonst lokal | verweigert | verweigert |
| `plan` | Cloud erlaubt | Cloud nur mit Freigabe | verweigert | verweigert |
| `code` | Cloud erlaubt | Cloud nur mit Freigabe (wie heute Coding-`plan`) | verweigert | verweigert |
| `research` | Cloud erlaubt | Cloud nur mit Freigabe (Suchanfrage kann persoenlich sein) | verweigert | verweigert |
| `vision` | nur ausdruecklich freigegebenes oeffentliches Bild: Cloud mit Freigabe | verweigert | verweigert | verweigert |
| `speech` | nicht durch diese Richtlinie (E4) | verweigert | verweigert | verweigert |

"Verweigert" heisst: kein Cloud-Aufruf; lokal nur, wenn ein lokales Modell die Klasse leisten kann, sonst klare Fehlermeldung (R4).

## Rueckfallverhalten bei Ausfall

| Fall | Verhalten |
|---|---|
| Lokales Modell nicht erreichbar / Zeitueberschreitung | Fehler mit Ursache an den Benutzer; **kein** Wechsel zur Cloud (R4). Wiederholung hoechstens im Rahmen der bestehenden Limits (`max_attempts_per_step` <= 5). Ziele/Schritte schlagen wie heute ueber ihre Fehlerpfade fehl. |
| Cloud nicht erreichbar, Schluessel fehlt, Limit erreicht | Aufruf scheitert mit Meldung; **kein** stilles Ausweichen auf ein anderes Cloud-Modell; ein Ausweichen auf lokal nur, wenn die Daten es erlauben **und** der Benutzer es sieht (R13); sonst Fehler. |
| Audit nicht schreibbar | Cloud verweigert, lokal erlaubt (R6). |
| Notaus aktiv | alle Modellaufrufe verweigert (wie heute). |
| Klassifizierung fehlgeschlagen/unklar | wie `never`: kein Cloud-Aufruf (R3). |
| Kein Modell fuer `vision` lokal | "nicht moeglich"; kein Cloud-Ersatz (R2). |

## Offene Entscheidungen (Besitzer)

| # | Frage | Empfehlung des Entwurfs |
|---|---|---|
| E1 | Soll Routing ueberhaupt kommen, oder bleibt es bei einem manuell gewaehlten Anbieter je Start? | Routing nur als schmale, standardmaessig ausgeschaltete Schicht |
| E2 | Wer legt Aufgabenklasse und Datenklasse fest: nur fest im Code je Aufrufer, oder zusaetzlich konfigurierbar je Modul? | fest im Code, konfigurierbar nur *strenger* |
| E3 | Darf `never` (Bildschirm, UI-Baum, Gedaechtnis) jemals mit ausdruecklicher Freigabe an die Cloud, oder gilt es absolut? | absolut `nie` bis zu einer eigenen Entscheidung je Datenart |
| E4 | Cloud-STT (Whisper-API) und Cloud-TTS: erlaubt, getrennt geregelt oder verboten? | verboten, bis entschieden |
| E5 | Kostenbegrenzung: nur Aufrufe/Token, oder auch Geld (braucht gepflegte Preistabelle je Modell und Waehrung)? Welche Zahlen (Aufrufe, Token je Aufruf/Sitzung)? | Aufrufe und Token zuerst, Kosten spaeter |
| E6 | Freigabe je Aufruf (R5) auch fuer `public`? Ist eine Sitzungsfreigabe "Cloud fuer diese Sitzung fuer `personal`" je erlaubt? | je Aufruf fuer `personal`, nie Sitzungsrecht |
| E7 | Welche Anbieter gelten als Cloud (nur `openai`/`anthropic`, oder jeder entfernte `openai_compatible`-Endpunkt, auch im LAN)? | alles ausser Loopback ist Cloud |
| E8 | Loopback-Dienste, die selbst weiterleiten (Proxy zu einer Cloud): wie erkennen? | nicht erkennbar; Besitzer traegt die Verantwortung, in der Doku benennen |
| E9 | Wie streng ist die Pruefung auf `secret` (nur Muster aus `redaction.py`, oder zusaetzlich Verweigerung bei Dateien aus Sperrlisten)? Akzeptable Fehlalarmrate? | beides, Fehlalarme in Kauf nehmen |
| E10 | Soll ein lokales Bildmodell Voraussetzung fuer `vision` sein, und welches? (Eigener Pruefbericht nach `docs/INTEGRATIONS.md` noetig.) | ja, getrennter Pruefschritt |
| E11 | Darf der Nutzer die Ausfall-Wiederholung ("lokal nochmal versuchen") im Chat anstossen, oder nur ueber Neustart? | nur ausdrueckliche Benutzereingabe |
| E12 | Audit-Ereignis `llm_route` in das bestehende Audit-Log oder eigener Sink? Aufbewahrung/Rotation (haengt an `audit-hash-chain`, nicht freigegeben)? | bestehendes Log |

## Abgrenzung und Grenzen dieses Entwurfs

- Keine Implementierung, keine Konfigurationsschluessel, keine Tests fuer neues Verhalten; `config/jarvis.toml` und alle Sicherheitslimits bleiben unveraendert.
- Die Matrix ist eine Absicht, kein Nachweis: Sie wird erst mit `llm-routing-policy` (und deren Tests, Strukturtest zur Kontrollstelle) verbindlich.
- Eine Erkennung geheimer oder personenbezogener Inhalte ist nie vollstaendig; die Richtlinie stuetzt sich deshalb vor allem auf die **Herkunft** der Daten, nicht nur auf Muster.
- Windows-spezifische Teile (Bildschirm, UI-Baum, Mikrofon) sind hier nur als Datenquellen benannt; ein Windows-Nachweis entsteht erst bei der Umsetzung ueber den CI-Windows-Lauf.
