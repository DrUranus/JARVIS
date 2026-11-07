# Entwurf: Bild-, Audio- und Videobearbeitung (`media-design`)

**Status: reiner Entwurf. Kein Code, nichts implementiert, nichts aktiviert, keine Abhaengigkeit aufgenommen** (`pyproject.toml` unveraendert). Dieses Dokument legt Kandidaten, Operationen, Argumentlisten, Grenzen und Abnahmetests fest, bevor ein Schritt `media-agent` ueberhaupt in Betracht kommt.

**Entscheidung des Besitzers erforderlich.** Der Entwurf trifft keine verbindliche Wahl und gibt nichts frei. `media-agent` bleibt **nicht freigegeben** (`docs/BACKLOG.md`) und braucht einen eigenen Backlog-Eintrag mit `approved: true`. Bis dahin gilt: kein Medien-Code, keine Konfiguration `[media]`, kein Tool `media`, kein FFmpeg-Aufruf.

## 1. Ausgangslage (belegt)

| Befund | Wo |
|---|---|
| Kein Medienbearbeitungs-Code im Repository; `media-agent` ist "vorbereitet, nicht freigegeben, erst nach Entwurf und Entscheidung des Besitzers" | `docs/BACKLOG.md` |
| Keine Laufzeit-Abhaengigkeiten (`dependencies = []`); Zusatzfunktionen sind optionale Extras, lazy importiert | `pyproject.toml` |
| Dateizugriffe nur im Workspace ("zwei Mauern": `coding.workspace_roots` **und** `security.allowed_roots`); `PathGuard` loest Symlinks auf | README "Dateisystem", "Coding Agent" |
| Alle Tool-Aktionen laufen ueber `ToolRegistry.execute` -> `PermissionEngine`; Verdrahtung nur in `src/jarvis/bootstrap.py` | `CLAUDE.md` |
| Analoge Entwuerfe: `docs/OFFICE_DESIGN.md` (Dateien im Workspace), `docs/SANDBOX_DESIGN.md` (Prozess-Isolation) | `docs/` |

Abgrenzung: Dieser Entwurf betrifft **Dateien** im Workspace (Bild, Audio, Video). Nicht Teil: Aufnahme von Kamera/Mikrofon/Bildschirm, Streaming, Netzwerk-URLs als Eingabe, Spracherkennung/-ausgabe (bestehende Sprachmodule), Bild-/Video-**Erzeugung** durch KI-Modelle (Cloud, Kosten), Inhaltsanalyse durch ein LLM.

## 2. Kandidaten und Lizenzen

Stand der Pruefung: 2026-11-07. Quellen: PyPI-JSON-Schnittstelle (`https://pypi.org/pypi/<paket>/json`), FFmpeg-Quelltext `LICENSE.md` und `doc/general_contents.texi` (`https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/...`), Buildseite von gyan.dev (`https://www.gyan.dev/ffmpeg/builds/`). **Nicht erreichbar** (Netzwerkgrenze der Sitzung): `ffmpeg.org/legal.html` und die BtbN-Projektseite; die Aussagen dazu stehen unter "nicht geprueft" und sind vor einer Aufnahme nachzuholen. Versionen aendern sich; vor Aufnahme neu pruefen und mit Ober-/Untergrenze festlegen. Die Angaben sind Metadaten, **keine Rechtspruefung**.

| Kandidat | Zweck | Version (PyPI) | Lizenz | Windows | Quelle |
|---|---|---|---|---|---|
| **FFmpeg** (externes Programm) | Audio/Video (und Bild) umwandeln, schneiden, skalieren | Build 8.1.2 (gyan.dev, "previous release"); Git-Builds vom 2026-11-02 | LGPL v2.1+ bei Standard-Konfiguration; GPL v2+ mit `--enable-gpl`; v3-Varianten mit `--enable-version3`; `--enable-nonfree` = nicht weitergebbar (siehe 2.2) | ja, statische Binaries | https://github.com/FFmpeg/FFmpeg (`LICENSE.md`), https://www.gyan.dev/ffmpeg/builds/ |
| **Pillow** | Bilder lesen/schreiben/skalieren in Python | 13.0.0 (2026-10-16) | MIT-CMU (PyPI `license_expression`) | ja (Wheels) | https://pypi.org/project/pillow/ |
| **opencv-python-headless** | Bild-/Videoverarbeitung (Filter, Erkennung) | 5.0.0.93 (2026-07-02) | Paketskripte MIT, OpenCV Apache-2.0 (laut Projektbeschreibung); Wheels liefern FFmpeg unter LGPLv2.1 mit; PyPI-Feld "Apache 2.0" | ja (Wheels) | https://pypi.org/project/opencv-python-headless/ |
| imageio-ffmpeg (nur zur Kenntnis) | buendelt ein FFmpeg-Binary fuer Python | 0.8.1 (2026-11-03) | BSD-2-Clause (Paket); gebuendeltes FFmpeg hat eigene Lizenz | ja | https://pypi.org/project/imageio-ffmpeg/ |

### 2.1 Bewertung

- **FFmpeg als externes Programm** (Empfehlung E1): groesster Formatumfang, eigener Prozess (Zeitlimit und Notaus per Prozessende erzwingbar), keine Python-Abhaengigkeit, keine Bindung im Prozess (relevant fuer die LGPL-Frage: Aufruf als getrenntes Programm, nicht Linken). Nachteil: Binary muss vom Benutzer bereitgestellt werden; grosse, komplexe Parser (Angriffsflaeche bei bösartigen Dateien).
- **Pillow** (E2, Bilder): reines Bild-Handling im Prozess, MIT-CMU, gut testbar ohne externes Programm; Bildbomben-Schutz (`Image.MAX_IMAGE_PIXELS`, `DecompressionBombError`) ist vorhanden und wird auf einen **Fehler** gestellt, nicht nur eine Warnung (Pruefung vor Aufnahme).
- **OpenCV**: nur als spaeterer Kandidat fuer Bildanalyse/Filter; gross (Binaerdateien), bringt ein eigenes FFmpeg mit (anderes Lizenz-/Update-Profil als das externe Programm). Fuer Stufe M1 **nicht** noetig.
- **imageio-ffmpeg / gebuendelte Binaries**: nicht empfohlen; die Herkunft des Binaries waere ein zweiter, schwer pruefbarer Vertrauenspunkt.

### 2.2 Lizenzvarianten von FFmpeg-Builds (belegt aus den genannten Quellen)

| Variante | Bedeutung | Quelle |
|---|---|---|
| **LGPL v2.1+ (Standard)** | Die meisten Dateien sind LGPL v2.1+; ohne weitere Optionen gilt LGPL v2.1+ fuer das Ergebnis. | `LICENSE.md` |
| **GPL v2+** | Optionale GPL-Teile (z. B. mehrere Filter) werden nur mit `--enable-gpl` aktiv; dann gilt GPL v2+ fuer den ganzen Build. Gilt auch fuer Bibliotheken wie libx264/libx265 (GPL). | `LICENSE.md`, `general_contents.texi` |
| **v3-Varianten (LGPL v3 / GPL v3)** | `--enable-version3` noetig, wenn Komponenten mit Lizenz "v3" eingebunden werden (z. B. OpenCORE-AMR); kombiniert mit `--enable-gpl` ergibt sich GPL v3. | `LICENSE.md`, `general_contents.texi` |
| **nonfree** | `--enable-nonfree` (z. B. Fraunhofer-AAC-Bibliothek, libmpeghdec): das Binary ist laut `LICENSE.md` **nicht weitergebbar**. | `LICENSE.md`, `general_contents.texi` |
| **gyan.dev "essentials" / "full"** | Laut Buildseite sind **alle Builds 64-bit, statisch und als GPLv3 lizenziert**; "full" enthaelt mehr Bibliotheken (u. a. libx264, libx265 und viele weitere); die Seite verlangt fuer eigene Builds kein `--enable-nonfree`. Zusaetzlich gibt es "full-shared" (DLLs). | https://www.gyan.dev/ffmpeg/builds/ |
| **BtbN-Builds** | Nicht geprueft (Seite war nicht erreichbar). Vor jeder Empfehlung an der Projektseite pruefen, welche GPL/LGPL-Varianten (gpl, lgpl, shared) angeboten werden. | nicht geprueft |

Folgerungen fuer JARVIS (Entwurf, nicht bindend):

1. **JARVIS liefert kein FFmpeg mit und laedt keines herunter.** Der Benutzer installiert FFmpeg selbst und traegt den absoluten Pfad in die Konfiguration ein (siehe 5). Damit entstehen keine Weitergabepflichten fuer JARVIS und keine Netzwerkzugriffe.
2. Der Aufruf als **getrenntes Programm** bindet JARVIS nicht an die FFmpeg-Lizenz; GPL-Builds sind fuer die private Nutzung zulaessig, eine **Weitergabe** eines Builds zusammen mit JARVIS waere eine eigene Lizenzfrage (E4).
3. Beim ersten Start des Tools wird `ffmpeg -version` (feste Argumentliste) gelesen und die Konfigurationszeile (`--enable-gpl`, `--enable-version3`, `--enable-nonfree`) im Audit vermerkt; die Lizenzvariante wird nur **angezeigt**, nicht bewertet.
4. Patentbehaftete Codecs (z. B. H.264/H.265/AAC) sind ein getrenntes, nicht rechtlich geprueftes Thema; die Operationsliste nutzt standardmaessig freie Formate (Opus, Vorbis, FLAC, WAV, VP9/AV1, PNG, WebP, JPEG) und listet H.264/AAC erst als Option (E5).

## 3. Stufen

| Stufe | Inhalt | Status |
|---|---|---|
| **M0** | Nichts (heutiger Zustand). | gilt |
| **M1 (Ziel von `media-agent`, nach Freigabe)** | Bilder mit **Pillow** (Info, Skalieren, Zuschneiden, Umwandeln); Audio und Video mit **FFmpeg** (Info, Umwandeln, Kuerzen, Audio extrahieren, Lautstaerke, Vorschaubild). Nur im Workspace, nur als neue Datei. | nach Freigabe |
| **M2 (spaeter, eigener Entwurf)** | OpenCV (Analyse/Filter), Zusammenfuegen mehrerer Quellen, Untertitel/Text einblenden (Schriftart, `drawtext`). | nicht Teil dieses Entwurfs |
| **M3 (spaeter, eigener Entwurf)** | Hardwarebeschleunigung, Netzwerkquellen, Aufnahme. | nicht Teil dieses Entwurfs |

Keine Stufe schaltet die naechste frei.

## 4. Operationsliste (M1) und feste Argumentlisten

### 4.1 Grundsatz: nie Kommandozeilentext

FFmpeg wird ausschliesslich mit `subprocess.run(argv, shell=False, ...)` und einer **Liste** gestartet; `argv[0]` ist der konfigurierte absolute Pfad. Jede Operation ist eine **Schablone** mit festen Optionen und benannten Platzhaltern. Es gibt **keine** Schablone aus Freitext, keine Zusammensetzung aus Modell-Ausgabe, kein `-filter_complex` aus Eingabe, kein `-f lavfi`, keine Rohoptionen des Benutzers. Platzhalterwerte werden vor dem Einsetzen geprueft (Typ, Wertebereich, Allow-List); ein ungueltiger Wert lehnt die Operation ab.

Gemeinsame feste Optionen jeder Schablone, in dieser Reihenfolge:

```
[ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
 "-protocol_whitelist", "file", "-threads", "<N>",
 ... operationsspezifisch ...,
 "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
 "-t", "<MAX_SEK>", "-fs", "<MAX_BYTES>", "-f", "<FORMAT>", "<AUSGABE_TEMP>"]
```

- `-nostdin`: keine interaktive Eingabe; `-n`: nie ueberschreiben; `-protocol_whitelist file`: nur lokale Dateien (kein `http`, `concat`, `tcp`, `pipe`, `subfile`); `-map_metadata -1`/`-map_chapters -1`: Metadaten werden nicht uebernommen (Datenschutz); `-sn -dn`: keine Untertitel- und Datenspuren; `-t`/`-fs`: harte Ausgabegrenzen (siehe 6).
- Eingabe immer als `"-i", "<EINGABE>"` mit **geprueftem, aufgeloestem** Pfad. Ein Pfad, der mit `-` beginnt, wird abgelehnt (keine Optionsverwechslung); der Pfad wird absolut uebergeben.
- Ein-/Ausgabe sind Dateien, nie `pipe:`, `-`, `http:`, `concat:`, `file:`-Praefix-Tricks oder Playlists (`.m3u8`, `.txt` mit `file '...'`-Zeilen) — Eingabeformat per Allow-List (4.4).
- Der Prozess erhaelt eine **bereinigte Umgebung** (kein `FFREPORT`, keine Proxy-/Token-Variablen), Arbeitsverzeichnis = Ausgabe-Temp-Ordner im Workspace, `stdout`/`stderr` begrenzt gelesen.

### 4.2 Operationen

Platzhalter: `E` Eingabe, `A` Ausgabe (immer neue Datei), `W/H` Pixel, `S/D` Sekunden, `dB` Dezibel. Alle Werte ganzzahlig oder als feste Dezimalzahl mit Bereichspruefung.

| ID | Operation | Engine | Feste Argumentliste (ab `-i`; gemeinsame Optionen aus 4.1 davor/danach) | Wertebereich |
|---|---|---|---|---|
| **I1** | Bildinfo | Pillow | kein Prozess; `Image.open` im Bildbomben-Limit, nur Format/Groesse/Modus | — |
| **I2** | Bild skalieren | Pillow | `thumbnail((W,H))` bzw. `resize`, Seitenverhaeltnis erhalten | 1 <= W,H <= 8192 |
| **I3** | Bild zuschneiden | Pillow | `crop((x0,y0,x1,y1))` | innerhalb der Bildgrenzen |
| **I4** | Bild umwandeln | Pillow | `save(A, format=F)`; EXIF wird **nicht** uebernommen | F in {PNG, JPEG, WEBP} |
| **A1** | Audio-/Videoinfo | FFmpeg-Familie | `[ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_entries", "format=duration,size:stream=codec_type,codec_name", "-of", "json", "-i", E]` | — |
| **A2** | Audio umwandeln | FFmpeg | `-i E -vn -c:a <C> -b:a <BR> -ar <SR> -ac <CH>` | C in {libopus, libvorbis, flac, pcm_s16le}; BR 32k-320k; SR in {16000,22050,44100,48000}; CH in {1,2} |
| **A3** | Audio kuerzen | FFmpeg | `-ss S -i E -t D -vn -c:a <C>` (Neu-Kodierung, kein `-c copy`) | 0 <= S, 0 < D <= Obergrenze |
| **A4** | Lautstaerke aendern | FFmpeg | `-i E -vn -af "volume=<dB>dB" -c:a <C>` — Filterstring aus Schablone, nur `<dB>` eingesetzt | -30 <= dB <= +20 |
| **V1** | Video umwandeln | FFmpeg | `-i E -c:v <CV> -crf <Q> -b:v 0 -vf "scale=<W>:<H>:force_original_aspect_ratio=decrease" -c:a <C>` | CV in {libvpx-vp9, libaom-av1}; Q 20-45; W,H 16-3840, gerade |
| **V2** | Video kuerzen | FFmpeg | `-ss S -i E -t D -c:v <CV> -c:a <C>` | wie A3/V1 |
| **V3** | Audio aus Video extrahieren | FFmpeg | `-i E -vn -map 0:a:0 -c:a <C>` | wie A2 |
| **V4** | Vorschaubild | FFmpeg | `-ss S -i E -frames:v 1 -vf "scale=<W>:-2" -f image2 A` | W 16-3840; Format PNG/JPEG |

`-vf`/`-af` werden **nur** als feste Schablonenstrings mit eingesetzten, geprueften Zahlen gebildet; ein Filter-Name oder -Argument aus Freitext ist ausgeschlossen. `<C>`, `<CV>`, `<F>` stammen aus Allow-Listen (kein beliebiger Codec-/Encoder-Name, kein `-c copy` mit unbekannten Streams). H.264/AAC (`libx264`, `aac`) sind erst nach E5 in die Allow-Liste aufzunehmen, und nur wenn der installierte Build sie anbietet.

### 4.3 Ausdruecklich ausgeschlossen

`-filter_complex`/`-lavfi` aus Eingabe, `-f lavfi`, `-f concat`, `-f tee`, `-i http(s)://`, `rtmp`, `tcp`, `udp`, `pipe:`, `-f data`/`-f image2` mit Platzhaltermustern (`%d`, `%03d`) fuer Eingabe oder Ausgabe (keine Dateiserien), `drawtext`/`subtitles`/`movie`/`amovie` (lesen weitere Dateien), `-attach`, `-dump_attachment`, `-report`, `-y`, `-extra_hw_frames`, jede Option, die Dateien liest oder schreibt, die nicht `E` oder `A` sind. Eine Schablone darf nur eine Eingabe und eine Ausgabe haben.

### 4.4 Eingabeformate (Allow-List)

Bild: `.png .jpg .jpeg .webp .gif`(erstes Bild) `.bmp`; Audio: `.wav .flac .ogg .opus .mp3`; Video: `.mp4 .mkv .webm .mov`. Pruefung am **Inhalt** (Magic Bytes / `ffprobe`-Formatname), nicht nur an der Endung; nicht uebereinstimmend -> Ablehnung. Container-Ketten und Playlists (`.m3u8`, `.sdp`, `.ffconcat`, `.txt`) sind ausgeschlossen (Dateileck- und SSRF-Technik ueber Playlists).

## 5. Konfiguration (Entwurf, nicht umgesetzt)

`[media]` mit `enabled = false` als Standard; unbekannte Schluessel werden abgelehnt. Vorgesehene Schluessel: `ffmpeg_path`, `ffprobe_path` (absolut, Datei muss existieren; kein Suchen im `PATH`, kein Download), `max_input_bytes`, `max_output_bytes`, `max_duration_seconds`, `max_pixels`, `timeout_seconds`, `threads`, `max_parallel_jobs`. Defaults siehe Tabelle 6. Ohne `ffmpeg_path` ist nur die Pillow-Teilmenge (I1-I4) verfuegbar, falls das Extra installiert ist.

## 6. Ressourcengrenzen (konservative Standardwerte, in der Konfiguration; nie ohne Grenze)

| Grenze | Standard (Vorschlag) | Durchsetzung |
|---|---|---|
| Eingabegroesse | 500 MB | `stat` vor dem Start; Ueberschreitung = Ablehnung |
| Ausgabegroesse | 500 MB | FFmpeg `-fs`; zusaetzlich Pruefung nach Ende, ueberschreitend = Ausgabe loeschen und Fehler |
| Dauer verarbeitet | 600 s Medienzeit | `-t`; Eingabedauer vorab per A1 gelesen, laenger = Ablehnung oder explizites Kuerzen |
| Laufzeit (Wanduhr) | 300 s | Prozess wird nach Ablauf beendet (Prozessbaum), Ausgabe-Temp wird geloescht |
| Bildpixel | 50 Mio. (z. B. 8192 x 6144) | Pillow `MAX_IMAGE_PIXELS` als Fehler; bei Video per `ffprobe` vor dem Start |
| Aufloesung Ausgabe | max. 3840 x 2160 | Schablonenbereich (V1, V4) |
| Rechenlast | `-threads` <= 4 (halbe Kernzahl, mind. 1) | Argument; unter Windows zusaetzlich Job-Object mit Speicher-/Prozessgrenze (Bezug `docs/SANDBOX_DESIGN.md`, falls umgesetzt) |
| Arbeitsspeicher | 2 GiB je Prozess | Job-Object (Windows) / `RLIMIT_AS` (Linux, Zusatz); ohne Durchsetzung ist die Grenze nur ein Wunsch und wird im Bericht so benannt |
| Parallele Jobs | 1 | Sperre im Tool |
| Ausgabe an Modell/Log | 8 KB Fehlertext, keine Medieninhalte | gekuerzt, Pfade relativ zum Workspace |
| Temp-Speicher | nur Ordner im Workspace, Obergrenze = Ausgabegrenze | wird nach Erfolg/Fehler/Notaus geloescht |

## 7. Anforderungen (verbindlich fuer einen spaeteren Schritt `media-agent`)

**B1 Standard aus.** `[media] enabled = false`. Kein Hintergrundlauf, keine Ordnerueberwachung, kein Selbststart, keine Ziele aus Medieninhalten (keine neue Autonomie).

**B2 Feste Argumentlisten.** Wie 4.1-4.4: `shell=False`, Liste, Schablonen, Allow-Listen, keine Rohoptionen. Ein Strukturtest stellt sicher, dass `subprocess` nur im Medienmodul und nur mit Liste und `shell=False` vorkommt.

**B3 Ausgabe nur im bestaetigten Workspace.** Eingabe **und** Ausgabe nur unter dem bestaetigten Workspace ("zwei Mauern": `coding.workspace_roots` und `security.allowed_roots`), aufgeloester echter Pfad (Symlinks, Junctions, Gross-/Kleinschreibung unter Windows); abgelehnt werden `..`, absolute Pfade ausserhalb, `~`, `:`/NTFS-Streams, Geraetenamen, UNC- und `\\?\`-Pfade ausserhalb. Das Zielverzeichnis muss existieren. Ohne gesetzten, bestaetigten Workspace -> verweigert. Ausgabe zuerst in eine temporaere Datei im selben Verzeichnis, danach atomares Umbenennen (`os.replace`); `-n`/exklusives Anlegen: **kein Ueberschreiben**, kein Loeschen bestehender Dateien. Geschuetzte Namen/Pfade (`.env`, `.git`, JARVIS-Repository, Abhaengigkeitsdateien) bleiben gesperrt. Der Pfad geht als `PATH`-Ressource an die Engine.

**B4 Berechtigungen.** Alle Operationen mindestens **YELLOW**; jede erzeugende Operation mit Einzelbestaetigung inkl. Eingabe, Ausgabe, Operation, Parametern, geschaetzter Groesse/Dauer. Sitzungsfreigabe nur fuer den Workspace. Ohne Rueckfragemoeglichkeit (`confirmation = "deny"`, Sperrmodus) verweigert. Notaus, Sitzungsbudget und Audit gelten wie bei allen Tools; Audit ohne Medieninhalt (Pfad, Operation, Groessen, Exit-Code).

**B5 Notaus und Zeitlimit.** Notaus beendet den FFmpeg-Prozess (Prozessbaum) und entfernt die temporaere Datei; Wanduhr-Limit wie Tabelle 6.

**B6 Bösartige Dateien.** Medien sind unvertrauenswuerdig: Groessen-/Dauer-/Pixelpruefung vor dem Start, Allow-Liste mit Inhaltspruefung, keine Playlists, kein Netzwerk. Ein Parser-Fehler (Exit-Code != 0, Absturz) ist eine saubere Ablehnung. Es wird empfohlen, FFmpeg aktuell zu halten (Sicherheitsluecken in Dekodern); die Version wird im Audit vermerkt.

**B7 Kein Netzwerk.** `-protocol_whitelist file`; ausserdem bei Windows-Umsetzung optional Firewall-/Job-Beschraenkung (Bezug Sandbox-Entwurf). Tests laufen ohne Netzwerk.

**B8 Prompt-Injection.** Metadaten, Dateinamen, Untertitel und Text in Medien sind **Daten**; sie loesen nie eine Aktion aus. Metadaten werden nicht uebernommen (`-map_metadata -1`).

**B9 Datenschutz / Routing.** Medien oder daraus gewonnene Texte gehen nur ueber die bestehende Routing-Richtlinie (`docs/LLM_ROUTING.md`) an ein Modell; kein stiller Cloud-Wechsel. Dieser Entwurf fuehrt keine Cloud-Uebertragung und keine Kosten ein. Lokale Verarbeitung ist der Normalfall (M1 braucht kein Modell).

**B10 Verdrahtung.** Neues Tool `media`, Registrierung ausschliesslich in `src/jarvis/bootstrap.py`; jede Aktion ueber `ToolRegistry.execute` -> `PermissionEngine`; kein zweiter Berechtigungsweg. Pillow als optionales Extra (`media = [...]`) mit Ober-/Untergrenze, lazy importiert; fehlt es oder FFmpeg, meldet das Tool klar, JARVIS startet normal.

## 8. Windows-Eignung

- Zielsystem Windows: FFmpeg-Windows-Builds sind statisch (gyan.dev) und laufen ohne Installation; Pillow-Wheels sind vorhanden. Linux ist nur Zusatzpruefung.
- Windows-spezifisch: gesperrte Dateien (Sharing-Violation als Meldung, nicht umgehen), Pfadlaenge, `\\?\`/Junctions (PathGuard), Prozessbaum beenden (Job-Object statt nur `terminate`), Kodierung von Dateinamen (Unicode-Argumente), Antiviren-Verzoegerung beim ersten Start.
- Windows-Nachweis liefert ausschliesslich der CI-Job `tests-windows`. Ob auf den CI-Runnern ein FFmpeg vorhanden ist, ist nicht geprueft; Tests mit echtem FFmpeg muessen ohne Netzwerk und ohne Download laufen (z. B. kleine eingecheckte Fixtures, Test wird sonst als **nicht ausgefuehrt** gefuehrt, nie als bestanden).

## 9. Abnahmetests (fuer einen spaeteren Schritt; keine Tests in diesem Schritt)

Alle ohne Netzwerk und ohne echte Schluessel. Argumentlisten-Tests brauchen **kein** FFmpeg (der Prozessstart wird durch eine Attrappe ersetzt, die `argv` aufzeichnet).

| Nr. | Test | Erwartung |
|---|---|---|
| T1 | Standard aus; unbekannter Konfigurationsschluessel | Tool nicht registriert bzw. Konfiguration abgelehnt |
| T2 | Attrappe zeichnet `argv` je Operation auf | `argv` ist Liste, `shell=False`, entspricht exakt der Schablone (Golden-Test je Operation) |
| T3 | Platzhalter mit Schadwerten (`-`-Praefix, Leerzeichen, `;`, `&`, `"` , `%d`, Newline, ausserhalb des Bereichs) | Ablehnung, kein Prozessstart |
| T4 | Verbotene Optionen/Filter/Protokolle (4.3) in jeder Eingabe | nie in `argv`; Ablehnung |
| T5 | Strukturtest: `subprocess` nur im Medienmodul, nur Liste; kein `shell=True`, `os.system`, `startfile` | gruen |
| T6 | Schreiben/Lesen ausserhalb des Workspace, `..`, absolut, `~`, NTFS-Stream, Geraetename, Symlink/Junction nach aussen | verweigert (gleiche Faelle Linux/Windows) |
| T7 | Kein bestaetigter Workspace | verweigert |
| T8 | Ausgabe existiert bereits | verweigert, Original unveraendert |
| T9 | Geschuetzte Namen/Pfade | verweigert |
| T10 | Eingabe zu gross / zu lang / zu viele Pixel / Bildbombe | vor dem Start abgelehnt |
| T11 | Playlist/`concat`/URL als Eingabe; Endung passt nicht zum Inhalt | abgelehnt |
| T12 | Zeitlimit (Attrappe haengt) | Prozess beendet, Temp geloescht |
| T13 | Notaus waehrend Lauf | Abbruch, keine halbe Zieldatei |
| T14 | Ausgabe ueberschreitet `max_output_bytes` | Ausgabe geloescht, Fehler |
| T15 | Bestaetigung: `deny`, Zeitablauf, Ablehnung | nichts geschrieben, kein Prozess |
| T16 | Audit | Pfad/Operation/Groesse/Exit-Code, **kein** Medieninhalt |
| T17 | Metadaten (EXIF/Tags) im Eingang | nicht in der Ausgabe |
| T18 | Dateiname mit Anweisungstext | loest nichts aus; als Daten behandelt |
| T19 | Fehlendes Extra / fehlendes FFmpeg | klare Meldung, JARVIS startet |
| T20 | Echter FFmpeg-Lauf mit kleiner Fixture (nur wenn Binary lokal vorhanden) | erwartete Ausgabe; sonst `not_run`, nie "bestanden" |
| T21 | Sicherheitsregression: `tests/test_*security*.py`, `tests/test_emergency_stop.py` | unveraendert gruen |
| T22 | Windows (nur `tests-windows`): gesperrte Datei, Junction, `\\?\`, Gross-/Kleinschreibung, Prozessbaum-Ende | wie T6/T8/T12, **Windows-Nachweis erst nach gruenem CI-Job** |

## 10. Offene Entscheidungen des Besitzers

| Nr. | Frage | Empfehlung |
|---|---|---|
| E1 | FFmpeg als externes Programm (statt Python-Bindung) | ja; Benutzer stellt Binary, absoluter Pfad in der Konfiguration, kein Download |
| E2 | Bildbibliothek fuer M1 | Pillow; OpenCV erst M2 |
| E3 | Zugelassene FFmpeg-Variante | beliebiger Build des Benutzers; Anzeige der Lizenzvariante im Audit; kein `nonfree` empfohlen |
| E4 | Weitergabe von FFmpeg mit JARVIS | nein (eigene Lizenzfrage) |
| E5 | Patentbehaftete Codecs (H.264/H.265/AAC) | zunaechst nicht; spaeter Allow-Liste nur auf Wunsch |
| E6 | Obergrenzen (Tabelle 6) | konservativ uebernehmen, in der Konfiguration |
| E7 | Betriebssystem-Isolation des FFmpeg-Prozesses (Job-Object, Speichergrenze) | an `docs/SANDBOX_DESIGN.md` koppeln; ohne Durchsetzung Grenzen nur als Wunsch ausweisen |
| E8 | Nachpruefung der nicht erreichbaren Quellen (`ffmpeg.org/legal.html`, BtbN) | vor Aufnahme nachholen |

## 11. Was dieser Schritt nicht tut

Kein Code, keine Tests, keine neuen Abhaengigkeiten, keine Konfiguration, kein FFmpeg-Aufruf oder -Download, keine Aenderung an `.github/`, `.claude/`, `CLAUDE.md`, `config/jarvis.toml` oder an Sicherheitslimits; keine Freigabe von `media-agent`.
