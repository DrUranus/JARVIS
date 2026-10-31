# pywinauto 0.6.9: Ergebnisse des Windows-Kompatibilitätstests

Bezug: `docs/integrations/windows-uia.md` (Prüfbericht, PR #60), PR #61, Workflow `.github/workflows/uia-compat.yml`, Dateien unter `ci/uia-compat/`.
Alle Angaben stammen aus dem tatsächlichen GitHub-Actions-Lauf **41225189506** (Commit `6c7e1f9`, 2026-10-31, `windows-latest` = Windows Server 2025, 10.0.26100). Linux-Läufe ersetzen dieses Ergebnis nicht. Es wurde nichts dauerhaft installiert: alles lief in einer temporären virtuellen Umgebung auf dem Runner.

## Ergebnis auf einen Blick

| | Python 3.13 (3.13.16) | Python 3.14 (3.14.10) |
|---|---|---|
| Auflösung nur aus Wheels mit den geprüften Hashes | bestanden | bestanden |
| Installation (`--require-hashes --only-binary=:all:`), `pip check` | bestanden | bestanden |
| Lizenz-, Lizenzdatei- und `.pth`-Prüfung | bestanden | bestanden |
| Import (`pywinauto`, `comtypes`, `pythoncom`, `win32api`, `six`) | bestanden | bestanden |
| COM/UIA-Wurzelelement | bestanden | bestanden |
| Fenster aufzählen | bestanden | bestanden |
| Echtes Notepad-Fenster finden und lesen | bestanden | bestanden |
| Lesen in einem eigenen Thread (Worker-Prozess) | bestanden | bestanden |
| Lesen aus einem fremden Thread (nur Hinweis) | hängt (20 s) | hängt (20 s) |
| Gegenprobe 1 (falsches Fenster) rot wie erwartet | ja | ja |
| Gegenprobe 2 (falsche Python-Version) rot wie erwartet | ja | ja |
| Gegenprobe 3 (Python ohne die Pakete) rot wie erwartet | ja | ja |

Gesamt: beide Legs der Matrix sind grün, die Gegenproben bestätigen, dass der Test bei fehlendem Fenster, falscher Python-Version und fehlender Bibliothek tatsächlich fehlschlägt. Es gibt im Test kein Überspringen.

## Abhängigkeits- und Sicherheitsprüfung (vor der Installation, mit Stopp bei Abweichung)

- **Auflösung:** `pip install --dry-run --require-hashes --only-binary=:all: --report` ergab genau vier Pakete, jeweils als Wheel: `pywinauto-0.6.9-py2.py3-none-any`, `six-1.17.0-py2.py3-none-any`, `comtypes-1.4.17-py3-none-any`, `pywin32-312` (`cp313`/`cp314`, `win_amd64`). Version, Wheel-Dateityp und der Hash aus `ci/uia-compat/requirements.txt` wurden gegen den Bericht geprüft; nichts war zurückgezogen. Weil nur Wheels installiert wurden, lief **kein `setup.py` und kein Quellpaket-Build**.
- **Lizenzen** (aus den installierten Paketen, `check_files.py`): `pywinauto` BSD 3-clause (`LICENSE` im Paket), `six` MIT (`LICENSE`), `comtypes` MIT (`licenses/LICENSE.txt`), `pywin32` PSF (mehrere Lizenzdateien). Weder Copyleft noch eine fehlende Lizenzangabe. Damit ist der in `windows-uia.md` offene Punkt "Lizenztext im installierten Paket" für diese vier Pakete mit den im Paket liegenden Lizenzdateien belegt, der Wortlaut wurde dabei nicht ins Dokument übernommen.
- **Installationsskripte:** `pywin32` bringt 30 Programme/Skripte unter `Scripts` mit (u. a. `pywin32_postinstall`, `pywin32_testall`), `comtypes` eines (`clear_comtypes_cache.exe`). pip führt diese bei der Wheel-Installation nicht aus; sie wurden in diesem Test nicht aufgerufen.
- **Pfaddatei mit Code-Zeile:** `pywin32.pth` enthält neben den Pfaden `win32`, `win32\lib`, `pythonwin` die Zeile `import pywin32_bootstrap`. Sie wird beim Start jedes Python-Prozesses dieser Umgebung ausgeführt. Der Test erlaubt ausschließlich genau diese bekannte Datei mit diesen Zeilen (jede andere `.pth`-Datei oder Zeile bricht ab). Das ist ein bekanntes Verhalten von `pywin32`, aber ein Punkt, den der Besitzer kennen sollte.
- **Datenabfluss:** In diesem Lauf wurde nur die Installation aus der Registry nachvollzogen. Netzwerkzugriffe der Pakete im Betrieb wurden **nicht** gemessen: offen.

## Was am echten Fenster belegt ist (beide Python-Versionen)

- Programm: klassisches Notepad der Runner-Umgebung. Gelesen wurden: Titel `Untitled - Notepad`, Typ `Window`, Prozess-ID, Rechteck 768×519, aktiviert, sichtbar, 26 Unterelemente (Typen `Button`, `Edit`, `MenuBar`, `MenuItem`, `ScrollBar`, `StatusBar`, `Text`, `Thumb`), ein `Edit`-Textfeld.
- `IsPassword` des Textfelds über die UIA-Eigenschaft (`CurrentIsPassword`) war lesbar und `False`. Damit ist belegt, dass die Passwortfeld-Eigenschaft über pywinauto erreichbar ist; ob sie bei einem echten Passwortfeld `True` liefert, wurde nicht getestet.
- Es gab ausschließlich lesende Aufrufe: keine Eingaben, Klicks, Prozessbeendigungen oder administrativen Aktionen; der Test prüft sein eigenes Skript darauf. Gestartet wurde nur Notepad.

## Befunde, die für den nächsten Schritt wichtig sind

1. **Thread-Bindung (belegt, beide Versionen):** Wird die im Hauptthread erzeugte UIA-Verbindung aus einem zweiten Thread benutzt, hängt der Aufruf (hier 20 s Zeitlimit, im ersten Lauf auch 60 s, auch mit `CoInitializeEx` im Thread). Läuft dagegen **alles in einem eigenen Thread, der die Verbindung auch erzeugt** (eigener Prozess), funktioniert das Lesen. Folge für JARVIS: Ein Provider braucht einen einzigen, dauerhaften Besitzer-Thread für alle UIA-Aufrufe; Aufrufer (Tools, Agenten) dürfen nie direkt aus ihren Threads zugreifen. Das muss im Entwurf von `uia-provider-readonly` stehen und mit einem Test abgesichert werden.
2. **Warnung beim Import:** `pywinauto/__init__.py:80: UserWarning: Revert to STA COM threading mode`. Der Import verändert den COM-Threadmodus des Prozesses (Einzelthread-Apartment). Das wirkt prozessweit und ist für die GUI (tkinter) und `comtypes` im selben Prozess zu bedenken: offen.
3. **Kein Fehler, aber Fakt:** Die Zeitdauer des ersten Testlaufs (je zwei Minuten) kam von den hängenden Querzugriffen, nicht von der Fenstersuche.

## Offene Probleme (nicht belegt)

- **Zielsystem:** Der Runner ist Windows Server 2025. Ob dasselbe auf dem Windows-11-PC des Besitzers gilt, ist nicht belegt. Die Microsoft-Seite nennt Windows 11 nicht ausdrücklich (siehe `windows-uia.md`).
- **Anwendungen:** Nur klassisches Notepad getestet. Moderne Anwendungen (WinUI/UWP, Electron, Browser, Office), Anwendungen mit höheren Rechten (UAC, Integritätsstufen) und echte Passwortfelder wurden nicht geprüft.
- **Schreibende Aktionen** (Invoke, Wert setzen) wurden absichtlich nicht getestet; das ist Aufgabe von `uia-actions`.
- **Python-Versionen:** 3.13 und 3.14 grün; Python 3.11 und 3.12 (laut `requires-python >= 3.11` erlaubt) sind nicht getestet, die `pywin32`-Hashes für diese Versionen fehlen weiterhin. Freie-Thread-Builds nicht getestet.
- **Dauerbetrieb:** Ein einzelner Lauf zeigt keine Stabilität über Stunden, keine Speicher- oder COM-Handle-Lecks.
- **Zusammenspiel mit JARVIS:** Es wurde nur die Bibliothek getestet, nicht die Einbindung in `ToolRegistry`/`PermissionEngine`, Notaus und Sitzungsbudget (das ist der nächste Schritt) und nicht das Zusammenspiel mit dem vorhandenen `win32`-Backend.
- **Beta 1.0.0b1 und andere Kandidaten** (`uiautomation`, UFO) wurden nicht getestet.

## Technische Eignung für `uia-provider-readonly`

**Technisch geeignet unter Bedingungen, kein Hindernis gefunden.** Belegt ist: Installation nur aus Wheels mit festen Hashes, saubere Lizenzlage der vier Pakete, Import, UIA-Wurzel, Fensterliste und das lesende Auslesen eines echten Fensters samt `IsPassword`, auf Python 3.13 und 3.14 unter Windows. Bedingungen für den Schritt: (1) ein einziger Besitzer-Thread für alle UIA-Aufrufe, (2) die COM-Threadmodus-Warnung im Entwurf behandeln, (3) die Tests an Windows 11 und an mindestens einer modernen Anwendung ergänzen, bevor Aktionen freigegeben werden, (4) die Besitzer-Freigabezeile in `windows-uia.md` bleibt Sache des Besitzers. Dieser Bericht trägt sie nicht ein.
