# M4 – Entscheidungsvorlagen D1–D8 (alle offen)

Keine Entscheidung wurde getroffen, nichts davon ist umgesetzt. Grundlage: `M4_SELF_IMPROVEMENT_LAB.md`. Gemeinsame Randbedingungen für **alle** Optionen: keine autonome Codeübernahme, `ExecutionGuard` bleibt gesperrt bis zum Isolationsnachweis auf der jeweiligen Plattform, `allow_prepare`/`allow_activation`/`repo_path` bleiben abgelehnt, `PermissionEngine`/Not-Aus/X0 unverändert, Windows-Nachweis nur durch den Windows-CI-Lauf.

## D1 – Sandbox-Backend je Plattform
- **Problem:** Ohne belegte Isolation (sieben Eigenschaften in `isolation.py`) darf kein Vorschlagscode laufen.
- **Optionen (sicher):** (a) Windows: Job Object + eingeschränktes Token/AppContainer in getrenntem Profil; (b) Windows Sandbox/Hyper-V-Gast; (c) Linux: `bubblewrap`/`nsjail`/Container ohne Netz (nur Zusatzprüfung); (d) **keine Ausführung** – das Lab bleibt rein bewertend (heutiger Stand).
- **Vor-/Nachteile:** (a) nativ, schnell, aber Netzsperre je Prozess und AppContainer-Start aus Python unerprobt; (b) starke Trennung, aber nicht in jeder Edition, langsam; (c) alle Eigenschaften erreichbar, aber kein Windows-Nachweis; (d) kein Risiko, aber auch keine getesteten Vorschläge.
- **Empfehlung:** (d) beibehalten, bis ein Prototyp von (a) oder (b) auf Windows alle sieben Eigenschaften per Test belegt; Auswahl nach Prototyp.
- **Auswirkung:** Erst mit Attest und grünem Windows-Lauf darf der Guard je Plattform entsperrt werden; bis dahin unverändert.

## D2 – Zustand `EXPORTED` statt `ACTIVATED`
- **Problem:** `ACTIVATED` suggeriert, JARVIS übernehme die Änderung selbst.
- **Optionen:** (a) neuer Endzustand `EXPORTED` („Paket zur manuellen Übernahme bereit“), `ACTIVATED` bleibt unerreichbar; (b) `ACTIVATED` umdeuten; (c) nichts ändern.
- **Vor-/Nachteile:** (a) ehrlich und Zustandsmaschine bleibt streng, aber Änderung an `state.py` (Phase-15-Schicht, durch Tests gepinnt); (b) verwirrend; (c) Begriff bleibt missverständlich, aber risikofrei.
- **Empfehlung:** (a), erst zusammen mit der Paketerzeugung.
- **Auswirkung:** Die Übergangstabelle ändert sich (ein Zustand, keine neue Aktivierungsmöglichkeit); Tests der Zustandsmaschine müssen erweitert, nicht abgeschwächt werden.

## D3 – Ort und Aufbewahrung des Patch-Pakets
- **Problem:** Das Paket enthält Code-Diffs; es darf weder ausführbar noch für JARVIS-Werkzeuge les-/anwendbar abgelegt werden.
- **Optionen:** (a) `self_improvement.data_dir` (liegt laut Konfiguration außerhalb aller erlaubten Wurzeln), Besitzerrechte; (b) eigenes Quarantäneverzeichnis; (c) nur im Speicher, Export per Befehl.
- **Vor-/Nachteile:** (a) vorhandene Regeln/Prüfungen, aber vermischt mit Vorschlagsspeicher; (b) klar getrennt, neue Konfiguration; (c) nichts bleibt liegen, aber nichts zum Prüfen bei Neustart.
- **Empfehlung:** (a) mit 30 Tagen Aufbewahrung und Löschung durch den Besitzer.
- **Auswirkung:** Keine Lockerung der Wurzel-Trennung; ein Test muss belegen, dass kein Werkzeug das Verzeichnis lesen kann.

## D4 – Schreibschutz der Installation
- **Problem:** Das Lab darf die Produktivinstallation nicht verändern können, auch nicht durch einen Fehler.
- **Optionen:** (a) Programmdateien schreibgeschützt (ACL), Daten/Konfiguration getrennt, Lab unter anderem Konto; (b) nur Konvention (Pfadprüfung in JARVIS); (c) Installation als Paket im Ordner des Besitzers wie heute.
- **Vor-/Nachteile:** (a) stärkste Wirkung, aber Installationsroutine und Updates komplizierter; (b) schwach (Software-Filter); (c) einfach, aber keine OS-Grenze.
- **Empfehlung:** (a) als dokumentierte Pflicht, sobald das Lab Code ausführen soll; vorher (c) zulässig, weil nichts ausgeführt wird.
- **Auswirkung:** Betrifft Installation/Updates (V2.0-Abnahme unberührt); keine Codeänderung in den Sicherheitsschichten.

## D5 – Sicherung des Vorschlagsspeichers
- **Problem:** Beschädigtes `proposals.json` führt heute fail-closed zu `IntegrityError`; Verlust möglich.
- **Optionen:** (a) Kopie vor jedem Zustandswechsel; (b) tägliche Kopie; (c) keine.
- **Vor-/Nachteile:** (a) lückenlos, mehr Schreibzugriffe; (b) einfach, Lücke bis 24 h; (c) heutiger Stand.
- **Empfehlung:** (a), HMAC-geschützt wie das Original, begrenzte Anzahl.
- **Auswirkung:** Neuer Schreibpfad im `data_dir` (selbe Rechte wie der Speicher).

## D6 – Verfahren zur Erweiterung von `ALLOWED_TARGETS`
- **Problem:** Die Erlaubnisliste (11 Dateien) begrenzt, was ein Vorschlag berühren darf; sie darf nie durch einen Vorschlag wachsen.
- **Optionen:** (a) nur per Besitzer-PR mit Begründung und Test, der die Liste pinnt; (b) Konfiguration; (c) nie.
- **Vor-/Nachteile:** (a) nachvollziehbar, Review-Last; (b) Konfig ist Angriffsfläche; (c) starr.
- **Empfehlung:** (a); die Lab-Sperrliste bleibt deckungsgleich mit `NEVER_TARGETS` (Test vorhanden).
- **Auswirkung:** Ein Test pinnt die Liste; jede Erweiterung ist sichtbar im Diff.

## D7 – Dürfen Tests eines Vorschlags ausgeführt werden?
- **Problem:** Vom Vorschlag mitgebrachte Tests können Anforderungen aufweichen oder Schadcode enthalten.
- **Optionen:** (a) nie; nur vertraute Tests aus dem Stand der Basis; (b) mitgebrachte Tests nur lesen/auswerten; (c) mitgebrachte Tests ausführen.
- **Vor-/Nachteile:** (a) verhindert „Test abschwächen, damit grün“; neue Tests müssen dann manuell übernommen werden; (b) wie (a) plus Analyse; (c) unsicher.
- **Empfehlung:** (a), Erweiterung auf (b) optional.
- **Auswirkung:** Passt zur Lab-Regel „übersprungen/verschwunden ≠ bestanden“; keine neue Ausführungsfähigkeit.

## D8 – Modellnutzung im Vorschlagsgeber
- **Problem:** Das Umformulieren von Vorschlägen sendet geschwärzte Beobachtungen an einen Anbieter.
- **Optionen:** (a) aus (`use_llm = false`, heutiger Stand); (b) lokal; (c) Cloud über Routing/Budget (`LLM_ROUTING.md`, `LLM_BUDGET.md`).
- **Vor-/Nachteile:** (a) kein Datenabfluss; (b) lokal, Qualität/Hardware; (c) beste Qualität, Datenabfluss und Kosten.
- **Empfehlung:** (a) beibehalten; (b) erst bei Bedarf; (c) nur mit ausdrücklicher Freigabe je Anbieter.
- **Auswirkung:** Bestehende Routing-/Budget-/Schwärzungsregeln gelten unverändert; Bearer-Schwärzung ist jetzt Teil des gemeinsamen Detektors.
