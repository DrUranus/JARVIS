<#  Sammelabnahme #186: fuehrt Schritt fuer Schritt durch die noch offenen Handpruefungen. Du tippst nur EINE Taste je Schritt: J = bestanden, N = nicht bestanden, S = ueberspringen.
    Das Skript entscheidet NIE selbst: ein Ergebnis entsteht ausschliesslich aus deiner Taste. Ohne -Execute ist es ein Trockenlauf (zeigt nur die Schritte).
    Es startet NEXUS (jarvis-cc) und die vorhandenen Hilfsskripte in deinem Benutzerkonto, installiert nichts, aendert weder Konfiguration noch Rechte noch Richtlinien,
    bedient nie UAC und erhoeht nie Rechte. Belege: <Out>\sammelabnahme.json und <Out>\sammelabnahme.md (Ordner ist ignoriert, nie committen; vor dem Anhaengen an #186 auf Schluessel pruefen).
    Aufruf: Doppelklick auf scripts\abnahme\Sammelabnahme-starten.cmd  (oder: powershell -File scripts\abnahme\sammelabnahme.ps1 -Execute)  #>
param([string]$Config = "config\nexus.voice-test.toml", [string]$Out = "abnahme-v2", [switch]$Execute)
$ErrorActionPreference = "Continue"
$py = ".\.venv\Scripts\python.exe"
$cc = ".\.venv\Scripts\jarvis-cc.exe"
if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ABBRUCH: Bitte in einer NICHT erhoehten PowerShell starten (Schritt S6 prueft genau das)." -ForegroundColor Red; exit 2 }
New-Item -ItemType Directory -Force $Out | Out-Null
$nodeDir = "C:\Program Files\nodejs"; if ((Test-Path $nodeDir) -and ($env:Path -notlike "*$nodeDir*")) { $env:Path += ";$nodeDir" }
$results = [ordered]@{}
$script:nexus = $null

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Wait-Enter($text = "Weiter mit Enter ...") { if ($Execute) { [void](Read-Host $text) } }
function Frage($id, $titel, $tun, $erwartung) {
    Say ""; Say "=== [$id] $titel" Cyan
    Say "  Tu das:   $tun"; Say "  Erwartet: $erwartung" Yellow
    if (-not $Execute) { $results[$id] = [ordered]@{ titel = $titel; ergebnis = "TROCKENLAUF"; notiz = "" }; return }
    Write-Host "  Ergebnis?  [J] bestanden   [N] nicht bestanden   [S] ueberspringen : " -NoNewline
    do { $k = ($Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown").Character.ToString()).ToUpper() } until ($k -in "J", "N", "S")
    $r = @{ J = "PASS"; N = "FAIL"; S = "SKIPPED" }[$k]
    Write-Host $r
    $note = ""; if ($r -eq "FAIL") { $note = Read-Host "  Was war falsch? (kurz, ohne Schluessel; Enter = leer)" }
    $results[$id] = [ordered]@{ titel = $titel; ergebnis = $r; notiz = $note; zeit = (Get-Date -Format s) }
}
function Zahl($id, $text) {
    if (-not $Execute) { Say "  (Eingabe: $text)" DarkGray; return }
    $v = Read-Host "  $text"; $results[$id + "-messwert"] = [ordered]@{ titel = $text; ergebnis = "MEASURED"; notiz = $v; zeit = (Get-Date -Format s) }
}
function Start-Nexus($extra) {
    if (-not $Execute) { Say "  TROCKENLAUF: $cc -c $Config --open $extra" DarkGray; return }
    if ($script:nexus -and -not $script:nexus.HasExited) { $script:nexus.Kill(); $script:nexus.WaitForExit(5000) | Out-Null }
    $psi = New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName = (Resolve-Path $cc).Path; $psi.Arguments = "-c `"$Config`" --open $extra"; $psi.UseShellExecute = $true
    $script:nexus = [System.Diagnostics.Process]::Start($psi); Start-Sleep -Seconds 6
}
function Run($what, [scriptblock]$block) { if (-not $Execute) { Say "  TROCKENLAUF: $what" DarkGray; return }; & $block }

Say "JARVIS Sammelabnahme #186 - ca. 45 Minuten. Du brauchst: Headset/Lautsprecher, Mikrofon, Notepad, Rechner, Einstellungen." Green
Say "Modus: $(if ($Execute) { 'ECHT (deine Tasten entscheiden)' } else { 'TROCKENLAUF (nichts wird gestartet)' })"
$env0 = [ordered]@{ commit = (git rev-parse HEAD); dirty = [bool](git status --short); windows = (Get-ComputerInfo).OsName + " " + (Get-ComputerInfo).OsVersion; date = (Get-Date -Format s); config = $Config }
Say "Stand: Commit $($env0.commit.Substring(0,7)), Arbeitsbaum $(if ($env0.dirty) { 'mit Aenderungen' } else { 'sauber' })"

# ---- A: NEXUS-Fenster (S1, B9) ---------------------------------------------------------------------------------------------------------
Say ""; Say "##### TEIL A: NEXUS-Fenster (kein Mikrofon noetig)" Green
Run "NEXUS starten" { Start-Nexus "" }
Frage "S1" "NEXUS startet" "Im geoeffneten Browserfenster hinschauen." "Oben steht 'verbunden' und 'bereit'; die Kugel (Orb) bewegt sich fluessig."
Frage "B9-1a" "Orb <-> Dashboard manuell" "Mit dem Umschalter zwischen Kugel und Dashboard hin und her wechseln." "Beide Ansichten erscheinen sofort, nichts hakt; auch die reduzierte 2D-Darstellung ist lesbar (kein 3D noetig)."
Frage "B9-1b" "Automatische Umschaltung" "Im Chat: Erstelle die Datei notizen.txt mit dem Inhalt: Hallo  (zustimmen), dann: Lies die Datei notizen.txt  und die Ansicht beobachten. Ein Wechsel nach Komplexitaet (ab 3 Schritten oder 2 Agenten) braucht einen mehrstufigen Auftrag, den diese Konfiguration (ohne Browser) nicht erzeugt: dann [S] druecken und das ehrlich als nicht pruefbar notieren." "Einfache Auftraege lassen die Ansicht stehen; nur ein echter mehrstufiger Auftrag schaltet selbst auf das Dashboard (sonst: uebersprungen, offen)."
Frage "B9-3c" "Freigabe: Schliessen = abgelehnt" "Chat: Erstelle den Ordner Abnahme3 ; wenn die Freigabefrage erscheint, den Browser-Tab SCHLIESSEN und danach die Seite neu oeffnen (Link im Terminalfenster von jarvis-cc)." "Der Ordner workspace\Abnahme3 existiert NICHT (Schliessen zaehlt als Ablehnen)."
Frage "B9-4a" "NOTAUS im Dashboard und in der Kugel" "In beiden Ansichten den roten NOTAUS-Knopf druecken." "Rotes Banner, neue Aktionen werden verweigert; danach ueber die Rueckfrage wieder aufheben."
Run "NEXUS mit Overlay neu starten" { Say "  Starte NEXUS neu mit dem kleinen Overlay (jarvis-cc --overlay --overlay-on-top) ..."; Start-Nexus "--overlay --overlay-on-top" }
Frage "B9-2" "Overlay: Groesse, im Vordergrund, Fokus" "Das kleine Fenster 'JARVIS' ansehen, ein anderes Fenster (Notepad) darueber oeffnen." "Etwa 140x140 gross, bleibt ueber anderen Fenstern, laesst sich verschieben."
Frage "B9-2b" "Overlay: Klick auf die Kugel oeffnet das Hauptfenster" "Auf den Kern des Overlays klicken." "Das NEXUS-Hauptfenster oeffnet sich im Browser."
Frage "B9-4b" "NOTAUS im Overlay" "Im Overlay den NOTAUS-Knopf (oben) druecken." "NEXUS zeigt das rote Not-Aus-Banner; danach wie vorher aufheben."
Frage "B9-3d" "Verbindungsverlust = abgelehnt" "Chat: Erstelle den Ordner Abnahme4 ; waehrend die Frage offen ist, das jarvis-cc-Fenster (Terminal) mit Strg+C beenden." "Nichts wird angelegt; nach Neustart gibt es workspace\Abnahme4 nicht."

# ---- B: Sprache (S2, S3, S4) -----------------------------------------------------------------------------------------------------------
Say ""; Say "##### TEIL B: Sprache (Headset aufsetzen)" Green
Run "NEXUS neu starten" { Start-Nexus "" }
Frage "S2a" "Sprache: Satz erkannt, Pegel bewegt sich" "Im Browser die Sprach-Taste druecken und einen Satz sagen, z. B. 'Wie spaet ist es'." "Der Pegelbalken schlaegt beim Sprechen aus, der Satz erscheint als Text, JARVIS antwortet (Mock-Antwort ist ok) und spricht."
Say "  Jetzt 5-mal denselben Satz sprechen und jeweils mit der Stoppuhr (Handy) messen: Satzende bis Text im Chat."
Zahl "S2b" "Median der 5 Zeiten in Sekunden (Zahl eintippen, Enter = ueberspringen)"
Frage "S2c" "Mikrofon abziehen" "Bei laufendem Sprachmodus den USB-Stecker des Mikrofons ziehen, das in voice.audio_device eingestellt ist, dann wieder einstecken." "Eine verstaendliche Meldung (kein Absturz, kein Haengen); Texteingabe geht weiter; nach dem Einstecken funktioniert die Sprache wieder."
Run "NEXUS beenden" { if ($script:nexus -and -not $script:nexus.HasExited) { $script:nexus.Kill() } }
Run "S3: deutscher Satz" { & $py -c "from jarvis.voice.windows_tts import WindowsTTS; WindowsTTS().speak('Dies ist ein deutscher Testsatz mit Umlauten: Groesse, Uebung und Faehre.')" }
Frage "S3a" "Sprachausgabe: deutscher Satz" "Den gesprochenen Satz anhoeren." "Deutsche Stimme (Hedda), verstaendlich, Umlaute klingen richtig."
Run "S3: befehlsaehnlicher Text" { $before = @(Get-Process powershell, python -ErrorAction SilentlyContinue).Count; & $py -c "from jarvis.voice.windows_tts import WindowsTTS; WindowsTTS().speak('Befehl: Get-Process; echo hallo `dir` und rm datei.txt')"; $after = @(Get-Process powershell, python -ErrorAction SilentlyContinue).Count; Say "  Prozesse vorher/nachher: $before / $after; datei.txt vorhanden: $(Test-Path .\datei.txt)" }
Frage "S3b" "Befehlsaehnlicher Text wird nur gesprochen" "Zuhoeren; oben steht die Prozesszahl und ob datei.txt entstand." "Wird nur gelesen; Prozesszahl gleich (+-1 fuer das Hilfsskript), datei.txt vorhanden: False."
Run "S4: Latenz hoerbar" { Say "  Gleich: 5 Laeufe. Je Lauf Enter (Sprache startet), dann ERNEUT Enter beim ersten Ton."; & $py scripts\abnahme\tts_first_sound.py --mode audible --out "$Out\04-tts-latenz-hoerbar.json" }
Frage "S4" "TTS-Latenz hoerbar gemessen" "Die 5 Laeufe des Hilfsskripts durchfuehren (Ergebnis steht in 04-tts-latenz-hoerbar.json)." "Werte liegen vor. Kein Zielwert: das Ergebnis ist nur MEASURED, nie PASS/FAIL gegen einen Wert."

# ---- C: Computersteuerung (S5, S6, S8c) --------------------------------------------------------------------------------------------------
Say ""; Say "##### TEIL C: Fenster lesen (S5/S6)" Green
Run "NEXUS starten" { Start-Nexus "" }
Frage "S5" "Notepad, Rechner, Einstellungen lesen" "Notepad, Rechner und Einstellungen oeffnen; im Chat je: Lies das Fenster Editor / Rechner / Einstellungen  (Freigaben mit Nein beantworten, wenn sie eine Eingabe wollen)." "Der Fensterinhalt wird gelesen oder klar abgelehnt, nichts wird getippt/geklickt, kein Haengen."
Frage "S6" "UAC (nur du)" "Notepad per Rechtsklick 'Als Administrator ausfuehren' selbst starten, UAC selbst entscheiden; dann im Chat: Lies das Notepad-Fenster." "Klare Ablehnung oder leerer Baum, kein Haengen; JARVIS selbst bleibt NICHT erhoeht."

# ---- D: Not-Aus bei Arbeit (S8) und Wiederaufnahme (S9) -------------------------------------------------------------------------------
Say ""; Say "##### TEIL D: Not-Aus bei laufender Arbeit und Wiederaufnahme" Green
Frage "S8a" "NOTAUS waehrend Sprachausgabe" "Sprachmodus an, JARVIS einen langen Satz sprechen lassen (z. B. 'Erzaehle mir ausfuehrlich, was ein Ordner ist'), waehrend er spricht NOTAUS druecken." "Die Ausgabe ist in hoechstens 1 Sekunde weg; danach in PowerShell: Get-Process powershell zeigt kein haengendes Fenster."
Frage "S8b" "NOTAUS waehrend eines Auftrags" "Einen mehrstufigen Auftrag starten und waehrend der Ausfuehrung NOTAUS druecken." "Weitere Schritte werden nicht ausgefuehrt; der Chat sagt es klar."
Run "NEXUS beenden" { if ($script:nexus -and -not $script:nexus.HasExited) { $script:nexus.Kill(); $script:nexus.WaitForExit(5000) | Out-Null } }
Frage "S9" "Harter Abbruch und Wiederaufnahme" "NEXUS starten, Auftrag beginnen, das jarvis-cc-Fenster hart schliessen (X), neu starten; im Chat: /resume  und dann /resume <Nummer>." "/resume listet nur; /resume <Nummer> fragt vor jedem Schritt mit Wirkung neu; in logs\audit.jsonl steht kein Schluessel (Select-String -Pattern 'sk-|Bearer ' ist leer)."
Run "NEXUS beenden" { if ($script:nexus -and -not $script:nexus.HasExited) { $script:nexus.Kill() } }

# ---- Ergebnis --------------------------------------------------------------------------------------------------------------------------
$ordered = [ordered]@{ umgebung = $env0; schritte = $results }
$ordered | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $Out "sammelabnahme.json")
$md = @("# Sammelabnahme #186 ($($env0.date)), Commit $($env0.commit.Substring(0,7))", "", "| Schritt | Titel | Ergebnis | Notiz |", "|---|---|---|---|")
foreach ($k in $results.Keys) { $v = $results[$k]; $md += "| $k | $($v.titel) | $($v.ergebnis) | $($v.notiz) |" }
$md | Set-Content (Join-Path $Out "sammelabnahme.md")
$fail = @($results.Values | Where-Object { $_.ergebnis -eq "FAIL" }).Count; $skip = @($results.Values | Where-Object { $_.ergebnis -eq "SKIPPED" }).Count
Say ""; Say "Fertig. Ergebnis: $Out\sammelabnahme.md  (FAIL: $fail, uebersprungen: $skip). Uebersprungen und nicht bestanden zaehlen NICHT als bestanden; die Entscheidung Go/No-Go trifft der Owner." Cyan
if (-not $Execute) { Say "TROCKENLAUF beendet: nichts wurde gestartet." Cyan; exit 0 }
exit ([int]($fail -gt 0))
