# NEXUS Ultimate · optionaler Control-Center-Client

Voraussetzungen und Windows-Installation stehen in `docs/NEXUS_GUI.md`. Im installierten Checkout:

```console
jarvis-cc -c config/nexus.example.toml --nexus-preview --open
```

Ohne Preview-Schalter öffnet sich V1. Mit **V1-Oberfläche** ist V1 auch in derselben Sitzung erreichbar. Der separate Workspace-Download enthält die lokale Demo. Die Projektbeispiele in den elf Premium-Ansichten sind lokal.

## Bedienung

Im Core-Modus übermittelt das Eingabefeld Text an den vorhandenen Controller. Eine Empfangsbestätigung bedeutet, dass der Controller den Auftrag angenommen hat. Antworten erscheinen im Gespräch. Der Vertrag liefert für gewöhnliche Texteingaben keine Zuordnung zwischen Befehls-ID und späterer Aufgaben-ID. Status und Ergebnisse von Aufgaben erscheinen deshalb unter der vom Backend gelieferten Aufgaben-ID. Ein Verbindungsabbruch löst keine automatische Wiederholung eines Auftrags aus.

Core und AI Core nutzen die vorhandene VoiceSession. Der Mikrofonknopf startet sie nur auf ausdrücklichen Klick. Abgelehnte Starts zeigen den Grund des Controllers. Bei unbekanntem Mikrofonzustand bleibt ein ausdrücklicher Stopp möglich. Hören, Verarbeitung, Sprechen, Arbeiten, Fehler, Freigabe und Not-Aus folgen Backendereignissen.

Overview, Agent Center und Live Workspace zeigen dieselben Aufgaben-, Agenten-, Ergebnis- und Journal-Panels wie V1. Schritt- und Fortschrittsangaben erscheinen nur, soweit das Backend sie liefert. Die Abbruchschaltfläche folgt der gemeldeten Abbrechbarkeit. Das Journal wird auf Nutzerwunsch geladen.

## Architektur und Abnahme

`nexus_preview/preview.js` verwendet die authentifizierte Sendefunktion des V1-Clients. V1 bleibt alleiniger Empfänger des SSE-Stroms und Besitzer der Bestätigungsdialoge. Während eines Dialogs ist die Premium-Fläche inert. Die Reset-Anfrage läuft über den Vertrag aus #264. Erst das Emergency-Ereignis aktualisiert die Zustandsanzeige. Die Live-Panels werden über einen Shadow-DOM-Slot dargestellt und bei der Rückkehr an ihrer V1-Position eingesetzt. Der bestehende Renderer und seine Fallbacks bedienen alle elf Ansichten.

Die Oberfläche ist ein Entwicklungskandidat. Für #186 und den separaten NEXUS-Hardwaretest sind Texteingabe, Fokus, Freigaben, Not-Aus, Fensterwechsel, Wiederverbindung sowie Spracheingabe und -ausgabe am Windows-Zielsystem zu prüfen. Mikrofon, Lautsprecher, physische GPU und interaktive Desktopabnahme sind PENDING. V1 bleibt Standard.
