<#  V2-Vorbereitung unter Windows: reproduzierbare, GEZIELTE Pruefung (keine volle Testsuite, keine GUI-Abnahme, keine Installation).
    Standard ist ein TROCKENLAUF: es wird nur ausgegeben, was ausgefuehrt wuerde. Mit -Execute laeuft es im aktivierten Projekt-venv (.venv).
    Es aendert weder Konfiguration noch Rechte noch Sicherheitsdefaults noch Git, erhoeht keine Rechte und startet kein JARVIS.
    Aufruf:  powershell -File scripts\v2\run-v2-prep-checks.ps1             (Trockenlauf)
             powershell -File scripts\v2\run-v2-prep-checks.ps1 -Execute    (echter Lauf, Protokoll in .\abnahme-v2-prep)
    Ein uebersprungener Test zaehlt hier als NICHT bestanden (Ausgabe -rfEs wird geprueft). Das Ergebnis ersetzt NICHT die interaktive Abnahme #186. #>
param([switch]$Execute, [string]$Out = "abnahme-v2-prep")
$ErrorActionPreference = "Continue"
$py = ".\.venv\Scripts\python.exe"
$tests = @("tests\test_v21_bootstrap_wiring.py", "tests\test_protected_files.py", "tests\test_agents_orchestrator_estop.py", "tests\test_v21_quality_gate.py", "tests\test_v21_quality_audit.py",
           "tests\test_v2_agent_conformance.py", "tests\test_v2_goal_retry_safety.py", "tests\test_nexus_feed.py", "tests\test_control_center_mission.py", "tests\test_v2_verify_defaults.py")
function Step([string]$what, [scriptblock]$block) {
    if (-not $Execute) { Write-Host "TROCKENLAUF: $what" -ForegroundColor DarkGray; return $null }
    Write-Host "== $what"; & $block
}
New-Item -ItemType Directory -Force $Out | Out-Null
$fail = 0
Step "python --version (nur lesend)" { & $py --version }
Step "verify_v2_defaults.py (alles Neue im Standard aus? Waechter intakt?)" {
    & $py scripts\v2\verify_v2_defaults.py | Tee-Object -FilePath (Join-Path $Out "defaults.json"); if ($LASTEXITCODE -ne 0) { $script:fail++ }
}
Step "pytest (gezielte Liste, kein Volllauf): $($tests -join ' ')" {
    & $py -m pytest -q -p no:cacheprovider -rfEs @tests --junitxml=(Join-Path $Out "v2-prep.xml") | Tee-Object -FilePath (Join-Path $Out "pytest.txt")
    if ($LASTEXITCODE -ne 0) { $script:fail++ }
    if (Select-String -Path (Join-Path $Out "pytest.txt") -Pattern "^SKIPPED" -Quiet) { Write-Host "UEBERSPRUNGENE TESTS gefunden: gilt als NICHT bestanden." -ForegroundColor Yellow; $script:fail++ }
}
if ($Execute) { if ($fail -eq 0) { Write-Host "ERGEBNIS: bestanden (nur diese gezielten Pruefungen, keine GUI-Abnahme)" -ForegroundColor Green } else { Write-Host "ERGEBNIS: $fail Pruefung(en) NICHT bestanden" -ForegroundColor Red; exit 1 } }
