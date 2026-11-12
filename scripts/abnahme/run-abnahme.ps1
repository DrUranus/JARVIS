<#  Orchestrierung der Windows-Abnahme #186 / V2 (Stand: auf Windows noch NICHT ausgefuehrt; Standard ist ein TROCKENLAUF, der nur ausgibt, was er tun wuerde).
    Fuehrt nur vorhandene Befehle aus (smoke, doctor, pytest, ci\uia-compat\check_uia.py, tts_first_sound.py), fragt Handschritte ab, schreibt Protokoll.
    Installiert nichts, aendert weder Konfiguration noch Rechte noch Sicherheitsdefaults. Ein uebersprungener Test = FAIL dieses Schritts.
    Aufruf:  powershell -File scripts\abnahme\run-abnahme.ps1                      (Trockenlauf: nichts wird gestartet)
             powershell -File scripts\abnahme\run-abnahme.ps1 -Execute [-Only S1,S3] [-NoManual]     (echter Lauf)
    Es gibt KEINE Funktion, die UAC bestaetigt, Rechte erhoeht, Konfiguration oder Richtlinien aendert oder etwas installiert.                                    #>
param([string]$Config = "config\nexus.example.toml", [string[]]$Only = @(), [switch]$NoManual, [switch]$Execute, [string]$Out = "abnahme-v2")
$ErrorActionPreference = "Continue"
$py = ".\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $Out | Out-Null
$results = [ordered]@{}
function Cmd([string]$what, [scriptblock]$block) {
    if (-not $Execute) { Write-Host "TROCKENLAUF: $what" -ForegroundColor DarkGray; return }
    & $block
}
function Want($id) { return ($Only.Count -eq 0) -or ($Only -contains $id) }

function Run-Pytest($id, $name, [string[]]$pytestArgs, [hashtable]$envVars = @{}) {
    $xml = Join-Path $Out "$id-$name.xml"
    if (-not $Execute) { Write-Host "TROCKENLAUF: $py -m pytest -q -rfEs $($pytestArgs -join ' ') --junitxml=$xml" -ForegroundColor DarkGray; return [ordered]@{ name = $name; verdict = "DRYRUN"; evidence = $xml } }
    foreach ($k in $envVars.Keys) { Set-Item "env:$k" $envVars[$k] }
    & $py -m pytest -q -rfEs @pytestArgs "--junitxml=$xml" 2>&1 | Tee-Object (Join-Path $Out "$id-$name.txt") | Out-Host
    $code = $LASTEXITCODE
    foreach ($k in $envVars.Keys) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
    $skipped = 0; $tests = 0
    if (Test-Path $xml) { [xml]$x = Get-Content $xml; $s = @($x.testsuites.testsuite); $tests = ($s | Measure-Object tests -Sum).Sum; $skipped = ($s | Measure-Object skipped -Sum).Sum }
    $verdict = if ($code -ne 0) { "FAIL" } elseif ($skipped -gt 0) { "FAIL (skip: $skipped)" } elseif ($tests -eq 0) { "FAIL (0 Tests)" } else { "PASS" }
    return [ordered]@{ name = $name; tests = $tests; skipped = $skipped; verdict = $verdict; evidence = $xml }
}

function Ask($id, $text) {
    if (-not $Execute) { Write-Host "TROCKENLAUF [$id] Handschritt: $text" -ForegroundColor DarkGray; return [ordered]@{ manual = "DRYRUN"; note = "" } }
    if ($NoManual) { return [ordered]@{ manual = "PENDING"; note = "" } }
    Write-Host "`n[$id] HANDSCHRITT: $text" -ForegroundColor Yellow
    do { $r = (Read-Host "Ergebnis (PASS/FAIL/NA)").ToUpper() } until ($r -in "PASS", "FAIL", "NA")
    $n = Read-Host "Notiz/Belegdatei (ohne Schluessel)"
    return [ordered]@{ manual = $r; note = $n }
}

# --- S0 Vorbereitung ------------------------------------------------------------------------------------------------------------------
$env0 = [ordered]@{ commit = (git rev-parse HEAD); dirty = [bool](git status --short); windows = (Get-ComputerInfo).OsName + " " + (Get-ComputerInfo).OsVersion;
    python = (& $py --version 2>&1) -join ""; date = (Get-Date -Format s); is_admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
if ($env0.is_admin) { Write-Host "ABBRUCH: Die Abnahme muss in einer NICHT erhoehten PowerShell laufen (S6 prueft genau das)." -ForegroundColor Red; exit 2 }
$env0 | ConvertTo-Json | Set-Content (Join-Path $Out "00-umgebung.json")

# --- S1 NEXUS starten -----------------------------------------------------------------------------------------------------------------
if (Want "S1") {
    $smoke = $null; $doc = $null
    Cmd "python ci\fresh-install\smoke.py; jarvis doctor" { & $py ci\fresh-install\smoke.py 2>&1 | Tee-Object (Join-Path $Out "01-smoke.txt") | Out-Host; $script:smoke = $LASTEXITCODE; & .\.venv\Scripts\jarvis.exe doctor 2>&1 | Tee-Object (Join-Path $Out "01-doctor.txt") | Out-Host; $script:doc = $LASTEXITCODE }
    $p = Run-Pytest "01" "server" @("tests\test_control_center_windows_smoke.py", "tests\test_control_center_server.py")
    $results.S1 = [ordered]@{ smoke = $smoke; doctor = $doc; pytest = $p; manual = (Ask "S1" "jarvis-cc --open starten, NEXUS zeigt 'verbunden' und 'bereit', Kugel laeuft fluessig; Screenshot als 01-nexus.png ablegen") }
}
# --- S2 Sprachaufnahme ------------------------------------------------------------------------------------------------------------------
if (Want "S2") {
    $p = Run-Pytest "02" "voice" @("tests\test_voice_stability.py", "tests\test_control_center_voice.py", "tests\test_control_center_voice_flow.py")
    Cmd "sounddevice.query_devices() (nur lesend)" { & $py -c "import sounddevice as sd; print(sd.query_devices())" 2>&1 | Tee-Object (Join-Path $Out "02-devices.txt") | Out-Host }
    $results.S2 = [ordered]@{ pytest = $p; manual = (Ask "S2" "Sprache starten, festen Satz sprechen: Pegel bewegt sich, Satz erkannt und beantwortet; Mikrofon ziehen: verstaendliche Meldung; Zeit bis Text (5x, Median) notieren") }
}
# --- S3/S4 TTS --------------------------------------------------------------------------------------------------------------------------
if (Want "S3") {
    $p = Run-Pytest "03" "tts" @("tests\test_voice_windows_tts_real.py", "tests\test_voice_windows_tts.py")
    $results.S3 = [ordered]@{ pytest = $p; manual = (Ask "S3" "voice.tts_provider=windows: deutschen Satz anhoeren (verstaendlich, Umlaute); befehlsaehnlicher Text (Semikolon, Backticks, Anfuehrungszeichen) wird nur gesprochen") }
}
if (Want "S4") {
    Cmd "tts_first_sound.py --mode wav (+ --mode audible)" { & $py scripts\abnahme\tts_first_sound.py --mode wav --out (Join-Path $Out "04-tts-latenz-wav.json") 2>&1 | Out-Host; if (-not $NoManual) { & $py scripts\abnahme\tts_first_sound.py --mode audible --out (Join-Path $Out "04-tts-latenz-hoerbar.json") } }
    $results.S4 = [ordered]@{ verdict = "MEASURED"; note = "kein Zielwert (G5/G7 offen)" }
}
# --- S5/S6 UIA und UAC ---------------------------------------------------------------------------------------------------------------------
if (Want "S5") {
    $p = Run-Pytest "05" "uia" @("tests\test_computer_uia_real.py", "tests\test_computer_uia_actions_real.py", "tests\test_computer_uia_notepad_e2e.py", "tests\test_computer_uia_halt.py", "tests\test_computer_uia_provider.py")
    $apps = @(@{ prog = "calc.exe"; re = "(?i)rechner|calculator" }, @{ prog = "mspaint.exe"; re = "(?i)paint" })
    $uia = @()
    foreach ($a in $apps) {
        if (-not $Execute) { Write-Host "TROCKENLAUF: check_uia.py (nur lesend) fuer $($a.prog)" -ForegroundColor DarkGray; $uia += [ordered]@{ program = $a.prog; exit = "DRYRUN" }; continue }
        $env:UIA_COMPAT_PROGRAM = $a.prog; $env:UIA_COMPAT_WINDOW_RE = $a.re; $env:EXPECT_PYTHON = "3.13"
        & $py ci\uia-compat\check_uia.py 2>&1 | Tee-Object (Join-Path $Out ("05-uia-" + $a.prog + ".txt")) | Out-Host
        $uia += [ordered]@{ program = $a.prog; exit = $LASTEXITCODE }
    }
    Remove-Item env:UIA_COMPAT_PROGRAM, env:UIA_COMPAT_WINDOW_RE, env:EXPECT_PYTHON -ErrorAction SilentlyContinue
    $results.S5 = [ordered]@{ pytest = $p; readonly_checks = $uia; manual = (Ask "S5" "Notepad (Win11), Rechner, Einstellungen: lesende Aktion und eine Freigabe-Aktion; Ablehnen fuehrt nichts aus; Notiz je App") }
}
if (Want "S6") {
    Cmd "whoami /groups (Integritaetsstufe, nur lesend)" { whoami /groups | Select-String -Pattern "Mandatory" | Tee-Object (Join-Path $Out "06-integritaet.txt") | Out-Host }
    $results.S6 = [ordered]@{ manual = (Ask "S6" "Notepad ueber das Kontextmenue 'Als Administrator ausfuehren' selbst starten und im UAC-Dialog SELBST entscheiden (dieses Skript bestaetigt oder bedient UAC nie); danach im Chat 'Lies das Notepad-Fenster': klare Ablehnung/leerer Baum, kein Haenger, JARVIS bleibt nicht erhoeht") }
}
# --- S7 Panel/Zeitleiste ----------------------------------------------------------------------------------------------------------------
if (Want "S7") {
    $p = Run-Pytest "07" "nexus" @("tests\test_control_center_timeline.py", "tests\test_control_center_approvals.py", "tests\test_control_center_confirmation.py")
    $e2e = $null
    $hasPw = $false; if ($Execute) { & $py -c "import playwright" 2>$null; $hasPw = ($LASTEXITCODE -eq 0) }
    if ($hasPw) { $e2e = Run-Pytest "07" "e2e" @("tests\test_control_center_e2e_browser.py", "-k", "timeline or approvals or e10") @{ JARVIS_GUI_EVIDENCE = (Join-Path $Out "gui") } }
    else { Write-Host "Playwright nicht installiert: Browser-E2E wird NICHT ausgefuehrt (nicht bestanden, Handschritt)." -ForegroundColor Yellow }
    $results.S7 = [ordered]@{ pytest = $p; e2e = $e2e; manual = (Ask "S7" "Mehrstufigen Auftrag starten: Panel 'Freigaben' (Liste, Frist, keine Knoepfe), Dialog ablehnen/ablaufen lassen/zustimmen, Zeitleiste mit Farben; Animationen-reduzieren an/aus") }
}
# --- S8 Not-Aus -------------------------------------------------------------------------------------------------------------------------
if (Want "S8") {
    $p = Run-Pytest "08" "notaus" @("tests\test_emergency_stop.py", "tests\test_voice_windows_tts.py")
    $n = Run-Pytest "08" "native" @("tests\test_control_center_native_windows.py") @{ JARVIS_NATIVE_GUI = "1" }
    Cmd "Get-Process (vorher)" { Get-Process powershell, python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime | Out-File (Join-Path $Out "08-prozesse-vorher.txt") }
    $results.S8 = [ordered]@{ pytest = $p; native = $n; manual = (Ask "S8" "(a) langen Text sprechen + NOTAUS: Ausgabe <= 1 s weg, kein haengendes powershell.exe (Get-Process); (b) langer Auftrag + NOTAUS; (c) UIA-Aktion + NOTAUS; (d) NOTAUS im Overlay") }
    Cmd "Get-Process (nachher)" { Get-Process powershell, python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime | Out-File (Join-Path $Out "08-prozesse-nachher.txt") }
}
# --- S9 Audit/Resume --------------------------------------------------------------------------------------------------------------------
if (Want "S9") {
    $p = Run-Pytest "09" "resume" @("tests\test_journal_hard_kill.py", "tests\test_journal_resume.py", "tests\test_cli_resume.py", "tests\test_session_budget.py")
    $results.S9 = [ordered]@{ pytest = $p; manual = (Ask "S9" "Auftrag starten, Prozess hart beenden, neu starten: '/resume' listet nur; '/resume <id>' fragt neu; Audit-Datei ohne Schluessel (Select-String -Pattern 'sk-|Bearer ' leer)") }
}

$results | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $Out "ergebnis.json")
$fail = ($results.GetEnumerator() | Where-Object { ($_.Value | ConvertTo-Json -Depth 6) -match '"FAIL' -or ($_.Value | ConvertTo-Json -Depth 6) -match '"manual":\s*"FAIL"' }).Count
if (-not $Execute) { Write-Host "`nTROCKENLAUF beendet: nichts wurde gestartet oder veraendert. Echter Lauf: -Execute" -ForegroundColor Cyan; exit 0 }
Write-Host "`nErgebnis: $Out\ergebnis.json  (FAIL-Schritte: $fail). PENDING/NA zaehlen nicht als bestanden." -ForegroundColor Cyan
exit ([int]($fail -gt 0))
