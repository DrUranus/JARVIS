# Checkliste: PC-Eignung für den isolierten Prototyp (Windows 11 Home)

**Zweck:** CPU, RAM, freien Speicher und Virtualisierung feststellen, bevor über einen Container- oder VM-Prototyp entschieden wird. **Alle Befehle sind nur lesend.** Nichts installieren, nichts im BIOS ändern, nichts aktivieren. Ergebnisse als Text an Claude zurückgeben (keine Screenshots mit persönlichen Daten nötig). Nach der V1-Abnahme #186, am Windows-PC. PowerShell normal starten (Start → „PowerShell“); wo „Admin“ steht, mit Rechtsklick „Als Administrator ausführen“. Schwellen unten sind **Richtwerte (Einschätzung)**, keine Herstellerangaben.

## 1. System und Edition (1 Min.)
```powershell
(Get-ComputerInfo -Property WindowsProductName,WindowsVersion,OsBuildNumber,OsArchitecture) | Format-List
```
Erwartet: „Windows 11 Home“, 64-Bit, Version/Build notieren (Docker nennt für Windows 11 mindestens 23H2/Build 22631).

## 2. CPU (1 Min.)
```powershell
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,VirtualizationFirmwareEnabled,SecondLevelAddressTranslationExtensions,VMMonitorModeExtensions | Format-List
```
Notieren: Modellname, Kerne/Threads. Richtwert: **mindestens 4 Kerne/8 Threads** (Rancher empfiehlt 4 CPU).
`VirtualizationFirmwareEnabled`, `SecondLevelAddressTranslationExtensions` (SLAT) und `VMMonitorModeExtensions` sollten `True` sein. **Achtung:** Läuft bereits ein Hypervisor (z. B. WSL 2), kann `VirtualizationFirmwareEnabled` `False` anzeigen, obwohl Virtualisierung an ist; dann Abschnitt 4 entscheidet.

## 3. RAM (1 Min.)
```powershell
$m = (Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum).Sum / 1GB; "{0:N1} GB installiert" -f $m
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='Frei_GB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}}
```
Richtwerte: **16 GB** wünschenswert (Rancher/Docker empfehlen 8 GB; der OpenHands-Container ist standardmäßig mit 4 GB RAM und 2 CPUs begrenzt, Windows und Browser brauchen zusätzlich). Unter 12 GB: VM-Prototyp unwahrscheinlich, Container nur mit kleinen Limits.
WSL beansprucht standardmäßig **50 % des RAM**; Datei `%UserProfile%\.wslconfig` existiert? 
```powershell
Test-Path "$env:USERPROFILE\.wslconfig"
```

## 4. Virtualisierung wirklich aktiv? (2 Min.)
Variante A (einfach): **Task-Manager** (Strg+Umschalt+Esc) → Reiter „Leistung“ → „CPU“: Zeile **„Virtualisierung: Aktiviert“**.
Variante B:
```powershell
systeminfo | Select-String -Pattern "Hyper-V|hypervisor|Virtualization|Virtualisierung"
```
Lesart: „A hypervisor has been detected“ = bereits aktiv (gut). „Virtualization Enabled In Firmware: Yes“ = im BIOS an. „No“ ohne erkannten Hypervisor = im BIOS/UEFI aus (Intel „VT-x“, AMD „SVM Mode“); **nicht jetzt ändern**, erst Rücksprache.
Windows-Funktionen (**Admin**):
```powershell
Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform,HypervisorPlatform,Microsoft-Windows-Subsystem-Linux | Select-Object FeatureName,State
```
Notieren, was „Enabled“ ist (nur lesen; nicht aktivieren).

## 5. WSL (1 Min.)
```powershell
wsl --version
wsl --status
wsl -l -v
```
Notieren: WSL-Version (Docker nennt ≥ 2.1.5), Standardversion 2, vorhandene Distributionen (Namen/Status). Falls „WSL nicht installiert“: so melden, nicht installieren.

## 6. Freier Speicher (1 Min.)
```powershell
Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{n='Frei_GB';e={[math]::Round($_.Free/1GB,1)}},@{n='Belegt_GB';e={[math]::Round($_.Used/1GB,1)}}
Get-PhysicalDisk | Select-Object FriendlyName,MediaType,@{n='Groesse_GB';e={[math]::Round($_.Size/1GB)}}
```
Richtwert: **mindestens 40 GB frei** auf dem Laufwerk, auf dem WSL/VM-Daten liegen sollen (Images, Verlauf, Platten-Datei); SSD (`MediaType`: SSD) stark empfohlen. Rancher nennt kein Plattenminimum.

## 7. Vorhandene Virtualisierungs-/Container-Software (1 Min.)
Nur auflisten, nicht deinstallieren:
```powershell
Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*,HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* | Where-Object { $_.DisplayName -match "Docker|Rancher|Podman|VirtualBox|VMware|Hyper|WSL|Windows Subsystem" } | Select-Object DisplayName,DisplayVersion
```
Wichtig wegen Koexistenz (VirtualBox neben aktiver Windows-Hypervisor-Plattform/WSL 2 hat laut Handbuch Leistungsprobleme).

## 8. Auswertung (zusammen mit Claude)
| Ergebnis | Folge |
|---|---|
| Virtualisierung aktiv, ≥ 16 GB RAM, ≥ 40 GB frei, ≥ 4 Kerne | Container-Prototyp (Rancher Desktop) kommt in Frage; VM zusätzlich möglich |
| Virtualisierung im BIOS aus | zuerst Rücksprache, dann BIOS-Einstellung (kein Eingriff vorher) |
| 8–12 GB RAM oder < 40 GB frei | nur kleiner Container-Prototyp oder gar nicht; VM eher nicht |
| VirtualBox/VMware bereits installiert | Koexistenz mit WSL 2 prüfen, bevor etwas installiert wird |
| WSL fehlt | als Voraussetzung melden (Installation braucht Admin; **nicht ohne Freigabe**) |

**Danach:** Eigene Freigabe des Besitzers für einen Wegwerf-Prototyp (Installation) einholen. Bis dahin: keine Installation, keine Ausführung von OpenHands, Coding bleibt bei der vorhandenen JARVIS-Implementierung.

## 9. Rückmeldung (Vorlage)
```
Edition/Build:            
CPU (Name, Kerne/Threads):            
SLAT / VMMonitorMode:            
Virtualisierung (Task-Manager):            
RAM installiert / frei:            
.wslconfig vorhanden:            
Funktionen (VMP/HypervisorPlatform/WSL):            
WSL-Version / Distributionen:            
Freier Speicher (Laufwerk, SSD?):            
Vorhandene Docker/Rancher/Podman/VirtualBox/VMware:            
```
