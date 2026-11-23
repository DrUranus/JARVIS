# V1-Restabnahme 2.3, 11.2, 14.1, 14.3 (lokal, Windows 11, Python 3.14.8, Branch `claude/v1-release`)
Ungefährliche Testdateien, keine Schlüssel, keine Live-Aufrufe, keine Änderung an Sicherheitsmechanismen. Skripte und Rohausgaben liegen lokal unter `abnahme-v2\v1\` (gitignored). Das sind lokale Belege des Prüfers, keine Owner-Handabnahme.

| Zeile | Ergebnis | Befehl | Ergebnis im Detail |
|---|---|---|---|
| 2.3 | PASS | `.venv\Scripts\python.exe -m pip install -e ".[dev,voice,ui]"`, danach `.venv\Scripts\jarvis.exe doctor` | pip Exit 0; Doctor vorher und nachher Exit 0, "0 Fehler, 0 Hinweis(e)", LLM `mock`, alle Schlüssel "nicht gesetzt", kein OneDrive-Pfad |
| 11.2 | PASS (mit Einschränkung) | `.venv\Scripts\python.exe abnahme-v2\v1\t112.py` (echter Kern, Auftrag `Lies die Datei gibtsnicht.txt`) | Ziel `FAILED`; Meldung: "Was fehlt: die angegebene Datei oder der Ordner / Warum es nicht weitergeht: sie existieren nicht … / Das kannst du tun: Pfad und Schreibweise prüfen …". Die Dashboard-Darstellung wurde nicht von Hand gesehen. |
| 14.1 | PASS | `.venv\Scripts\python.exe -u abnahme-v2\v1\t141.py`: 10 Zyklen: NEXUS starten (`config\nexus.example.toml`), Port prüfen, harmlosen Auftrag senden (Ack ok), Prozess hart beenden | In allen 10 Zyklen: Start ok, Auftrag angenommen, Port danach geschlossen, kein Launcher-Prozess übrig (Ports 59083 … 63168). Vorher liefen keine Launcher. Strg+C wird nicht geprüft (hartes Beenden). |
| 14.3 | PASS (mit Einschränkung) | `.venv\Scripts\python.exe abnahme-v2\v1\t143.py` (Datei exklusiv gesperrt, Auftrag `Lies die Datei gesperrt.txt`) | Direkter Zugriff `PermissionError`; Auftrag nach 2 Versuchen `FAILED` ("cannot read the file (PermissionError)"), kein Absturz, kein Traceback, Datei unverändert. Die Meldung ist technisch und nennt die Sperre nicht. |

Nicht geprüft: 14.2 (N/A, Recherche auf V2), Excel als sperrendes Programm (stattdessen exklusive Windows-Dateisperre), Dashboard-Optik.
