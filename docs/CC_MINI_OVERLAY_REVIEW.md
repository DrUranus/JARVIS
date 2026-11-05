# NEXUS Mini-Overlay: gezielte Technik- und Freigabepruefung (2026-11-05)

Status: **Besitzerentscheidung vom 2026-11-05: Option A freigegeben, ausschliesslich bedingt und optional.** Die begrenzte Implementierung auf einem Feature-Branch darf nach der dokumentierten Vorpruefung beginnen; Windows-Nachweise werden **an diesem Implementierungs-PR vor Merge** erbracht. Kein Windows-Nachweis vor Existenz des zu pruefenden Codes erforderlich.

## Anlass
Die Kettenauftraege #159 und #161 (cc-windows-start) konnten die Kriterien 4 und 5 nicht erfuellen: natives Mini-Overlay fehlt, und Not-Aus-Erreichbarkeit bei geschlossenem Hauptfenster ist nicht nachgewiesen. Der Doctor/Schnellstart ist bereits auf main. Ein erneuter Routine-Start ohne Entscheidung wiederholt den Blocker.

## Bestehende Evidenz (B0, 2026-11-04)
Siehe `docs/integrations/control-center-ui.md`, Anhang A-C:
- pywebview 6.2.1 (BSD-3-Clause) mit WebView2 ist ein moeglicher **optionaler** Windows-Fenster-Host. Die vorhandene Pruefung nennt sieben transitive Python-Pakete, darunter `proxy_tools` (letzte Veroeffentlichung 2014). Windows-Laufzeit, Telemetrie/Runtime-Lizenz und GitHub-Advisories sind noch nicht ausreichend belegt.
- `frameless`, `easy_drag`, `on_top` und kleine Fenster sind laut API-Dokumentation vorgesehen; **transparente Fenster sind auf Windows laut gepruefter Dokumentation nicht unterstuetzt**. Ein pywebview-Overlay waere daher rechteckig, nicht rund/freigestellt.
- Der bereits freigegebene Standardbibliothek-/Browserpfad und Canvas-2D-Fallback funktionieren ohne neue Pflichtabhaengigkeit. Ein zweiter nativer Fensterpfad ist bislang **nicht** freigegeben.

## Begrenzte Empfehlung
**Technikpruefung vor Freigabe**: pywebview als optionales Extra auf Windows in isolierter, nicht produktiv verdrahteter Testumgebung validieren; alternativ einen Browser-App-Fensterpfad anhand offizieller Windows-/Edge-Dokumentation evaluieren. Kein neuer nativer Fenster-Host wird durch dieses Dokument freigegeben.

### Noch zu erbringende Nachweise
1. Offizielle Lizenz-/Sicherheitsquellen fuer pywebview 6.2.1, WebView2-Runtime, pythonnet und transitive Pakete; Risiken des seit 2014 unveraenderten `proxy_tools` bewerten.
2. Windows 10/11 und Python 3.11-3.14: Installations-/Importprobe, WebView2-Erkennung, Fensterstart/-ende, Performance und fehlende Runtime; kein automatischer Download.
3. Kleines verschiebbares, **rechteckiges** Overlay (ca. 140x140), optional always-on-top, standardmaessig aus; kein Click-through und keine undokumentierten Windows-API-Hacks.
4. Ausschliesslich lokale Assets und bestehenden Loopback-Server mit Token, Host-/Origin-Pruefung, CSP, Limits; **keine** pywebview-JS-Python-Bruecke, kein Debug, keine Remote-Inhalte.
5. Not-Aus jederzeit sichtbar im Overlay, auch bei offenen Rueckfragen; pruefen, was bei Schliessen/Absturz des Hauptfensters und beim Verbindungsverlust passiert. Der bereits bestehende unabhaengige Not-Aus muss weiterhin funktionieren. Offene Freigaben werden bei Trennung abgelehnt.
6. Zielgerichtete Windows-CI- und GUI-Tests mit dokumentierten Ergebnissen; Linux-Tests gelten nicht als Windows-Nachweis. Keine Aenderung von PermissionEngine, X0, Not-Aus oder Merge-Gates.

## Besitzerentscheidung (noch offen)
- [x] **Option A:** Rechteckiges, nicht klickdurchlaessiges Mini-Overlay mit optionalem pywebview-Extra nach erfolgreicher Technikpruefung freigeben.
- [ ] **Option B:** Kein pywebview; Browser-Oberflaeche behalten, natives Mini-Overlay als gesonderten spaeteren Schritt planen.
- [ ] **Option C:** Andere Fenstertechnik erst gesondert pruefen.

**Besitzer-Freigabe: 2026-11-05.** Der Besitzer hat im Chat ausdruecklich pywebview fuer das optionale rechteckige Mini-Overlay freigegeben (Option A). Die Freigabe umfasst die begrenzte technische Validierung und nach dokumentierter Lizenz-/Abhaengigkeits-Vorpruefung die optionale Implementierung **auf einem isolierten Feature-Branch** mit den oben genannten Schutzmassnahmen. Die Windows-/Not-Aus-Nachweise werden **am Implementierungs-PR in Windows-CI vor Merge oder produktiver Nutzung** erbracht. Bei negativem Lizenz-/Sicherheitsbefund stoppen und eskalieren; fehlende Windows-Testergebnisse vor Erstellung des Implementierungscodes sind kein Freigabeblocker. Keine stillschweigende Ausnahme fuer fehlgeschlagene Tests. Kein Zwangs-Dependency, kein Click-through, keine JS-Python-Bruecke, keine Aenderung von PermissionEngine, X0, Not-Aus oder Merge-Gates. Die bisherige Freigabe fuer Stufe 1 bleibt bestehen. Diese Dokumentation startet keinen Workflow und setzt einen blockierten Auftrag nicht automatisch fort.


## Ablaufkorrektur nach Blocker #164 (2026-11-05)
Der Auftrag #164 konnte kein Windows-Overlay testen, weil der zu testende Code noch nicht existiert; die vorherige Formulierung verlangte Windows-Nachweise **vor** Implementierung. Das war ein zirkulaerer Blocker. Verbindliche Reihenfolge fuer den naechsten begrenzten Auftrag: (1) Quellen/Abhaengigkeiten und WebView2-Anforderungen soweit ohne Windows moeglich pruefen, Risiken dokumentieren; (2) falls kein kritischer Befund, optionales Overlay ausschliesslich auf Feature-Branch implementieren, standardmaessig aus; (3) gezielte Linux-Tests und Windows-CI fuer Overlay/Not-Aus ausfuehren; (4) bei Fehlschlag bis zu drei gezielte Korrekturen, keine Testabschwaechung; (5) nur bei bestandenen verpflichtenden Nachweisen PR mergen. Ein Linux-Runner ohne Windows ist **kein** Grund, vor Schritt 2 `needs_human` zu melden. Kann die CI den erforderlichen Windows-GUI-Nachweis nicht erbringen, konkreten Infrastruktur-Blocker mit Log dokumentieren und vor Merge stoppen. Bereits erfuellte Doctor-/README-Kriterien nicht erneut implementieren. Keine Aenderung an X0, PermissionEngine oder Not-Aus.
