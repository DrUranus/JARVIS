# Prüfdatei: Windows-Sprachausgabe mit Windows-Bordmitteln (PowerShell 5.1 + System.Speech)

**Stand: Prüfung (WP05 Teil A), nur Dokument. Nichts wurde installiert, ausgeführt oder verdrahtet.** PowerShell/`System.Speech` wurde nicht gestartet; alle Angaben stammen aus Herstellerseiten und dem Repository-Code. Umsetzung (Teil B) braucht eine gesonderte Owner-Freigabe (E8). Schema: `docs/INTEGRATIONS.md`, Test: `tests/test_integration_docs.py`.

## Name und Zweck
**Windows-Bordmittel für Sprachausgabe:** das mit Windows ausgelieferte **Windows PowerShell 5.1** (`powershell.exe`) lädt die .NET-Framework-Assembly `System.Speech` und spricht Text über `System.Speech.Synthesis.SpeechSynthesizer` (Microsoft Speech API, lokale SAPI-Stimmen). Zweck: eine **lokale** Sprachausgabe unter Windows 11 Home **ohne Zusatzinstallation**, später als `voice.tts_provider = "windows"`. Heutiger Stand im Repository: `voice/system_tts.py` kennt als Befehle nur `espeak-ng`, `espeak`, `spd-say`, `say` – unter Windows gibt es ohne Zusatzprogramm keine lokale Sprachausgabe (`VoiceUnavailableError`); `openai`-TTS sendet Text an die Cloud und bleibt ausgeschlossen (E4 in `docs/LLM_ROUTING.md`).
Es ist **kein Python-Paket** und **keine neue Abhängigkeit**.

## Lizenz (Wortlaut)
Windows PowerShell und das .NET Framework sind Bestandteile von Windows und unterliegen der **Windows-Lizenz**; deren Wortlaut wurde **nicht gelesen** (für den privaten und künftigen gewerblichen Einsatz eines bereits lizenzierten Windows ist keine zusätzliche Lizenz zu beschaffen – das ist eine Annahme, keine Rechtsauskunft). Zur Kenntnis (wird **nicht verwendet**): das NuGet-Paket `System.Speech` nennt „System.Speech is released as open source under the MIT license.“ (nuget.org, Stand 2026-11-10).

## Version und Datum
- **Windows PowerShell:** „The latest version is Windows PowerShell 5.1.“ („What is Windows PowerShell“, ms.date 2025-11-20). Welche Build-/Patchstufe der PC des Besitzers hat: **unbekannt** (die Checkliste `docs/V2_WINDOWS_PC_CHECKLISTE.md` erfasst die Windows-Version).
- **Klasse `SpeechSynthesizer`:** Doku zuletzt aktualisiert 2026-07-01; verfügbar in .NET Framework 3.0 bis 4.8.1.
- **Nicht verwendet:** NuGet `System.Speech` 11.0.0 (2026-11-10), Ziel .NET Standard 2.0/net10.0/net11.0, „Not supported on other platforms“, „provided primarily for compatibility with code being ported from .NET Framework and is not accepting new features.“

## Pflege
Pflege durch Microsoft über Windows-Updates (Windows PowerShell 5.1 ist „the version of PowerShell that ships in Windows“). Neue Funktionen für `System.Speech` sind laut NuGet-Seite nicht vorgesehen; die API ist stabil, aber veraltet. Aussagen zu Support-Zeiträumen wurden **nicht gelesen**.

## Python- und Windows-Kompatibilitaet
- **Python:** keine Abhängigkeit; Aufruf später per `subprocess` (Python ≥ 3.11).
- **Windows 11 Home:** Windows PowerShell 5.1 „ships in Windows“; ob jede Edition (Home eingeschlossen) und jede Build-Stufe es enthält, ist auf den gelesenen Seiten **nicht ausdrücklich dokumentiert** → durch den Runner-Test (Teil B) und die Owner-Abnahme zu belegen.
- **Stimmen:** `GetInstalledVoices()` listet „installed speech synthesis voices“; welche Stimmen (z. B. deutsch) auf dem PC vorhanden sind, hängt von den installierten Sprachpaketen ab (**nicht dokumentiert**). Ob neuere „natürliche“ Stimmen (Narrator/WinRT) für `System.Speech` sichtbar sind, ist **nicht dokumentiert**; die WinRT-Alternative `Windows.Media.SpeechSynthesis` („Only Microsoft-signed voices installed on the system can be used“) wurde bewertet und **nicht gewählt** (asynchron, aufwendigere Einbindung aus PowerShell).
- **Linux/CI:** nicht anwendbar; Linux-Läufe können nur Fake-Läufer prüfen. **Windows-Nachweis:** Runner-Test `windows-latest` (Teil B) – ob der Runner eine Stimme hat, ist **ungeprüft**.

## Transitive Abhaengigkeiten
Keine Python-Pakete. Systemkomponenten: `powershell.exe` (Windows PowerShell 5.1) und `System.Speech.dll` (.NET Framework). Keine NuGet-/pip-Installation, keine Downloads.

## Sicherheitshinweise
1. **Externer Prozess:** Teil B startet `powershell.exe` – das ist eine Prozessstart-Fläche und braucht Owner-Freigabe (E8). Der Start geschieht nie über eine Shell (`shell=False`), nur mit **fester Argumentliste**.
2. **Text niemals als Argument oder in den Skripttext:** der zu sprechende Text geht **ausschließlich über Standardeingabe** als **Daten**. **Achtung:** laut `about_PowerShell_exe` bedeutet `-Command -` bzw. `-File -`, dass PowerShell die Standardeingabe als **Code** liest („the commands are read from standard input“). Das ist **verboten**: der Befehl muss ein **fester, inline übergebener Skripttext** sein, der den Text als Daten liest. Ob das Lesen per `[Console]::In.ReadToEnd()` oder `$input` funktioniert, ist auf den gelesenen Seiten **nicht dokumentiert** → Pflicht-Test auf dem Runner (Injektionstest: Text wie `'; New-Item …` darf **keine** Datei anlegen).
3. **Kodierung:** `[Console]::InputEncoding` steuert, wie die Konsole Eingaben liest; der Standardwert unter Windows ist **nicht dokumentiert** → Skript setzt die Eingabekodierung ausdrücklich auf UTF-8 und der Runner-Test prüft Umlaute.
4. **Ausführungsrichtlinie:** nicht anfassen. **Kein** `-ExecutionPolicy Bypass`; Microsoft: „The execution policy isn't a security boundary, it's defense in depth.“ Ob ein inline übergebener `-Command` der Richtlinie unterliegt, ist **nicht dokumentiert** → durch den Runner-Test belegen; schlägt er fehl, ist das ein Grund zum Stopp, nicht zum Umgehen.
5. **Weitere feste Schalter:** `-NoProfile` („Doesn't load the PowerShell profile“), `-NonInteractive` (keine Rückfragen/Hänger). Eingabeformat Text.
6. **Begrenzungen:** Textlänge begrenzt, Steuerzeichen entfernt, Zeitlimit, Prozessbaum bei Notaus/Zeitüberschreitung beenden (vorhandenes Job-Object-Muster aus `self_improvement/winjob.py` bzw. Halt-Guard), Fehlermeldungen ohne Textinhalt (keine Geheimnisse in Logs).
7. **Nicht** installieren, keine Sprachpakete nachladen, keine Registry-Änderung.

## Datenabfluss
Der Provider selbst sendet nichts. Ob die Windows-Sprachausgabe (SAPI-Stimmen) ein Netzwerk nutzt, ist auf den gelesenen `System.Speech`-Seiten **nicht dokumentiert**; `System.Speech` greift laut Beschreibung auf „installed speech synthesis engine[s]“ zu. Verifikation: Netzmitschnitt ist **nicht** Teil dieser Prüfung. Cloud-TTS (`openai`) bleibt unabhängig davon aus.

## Pinning mit Hash
Nicht anwendbar (kein Paket, kein Download). Stattdessen wird das **Verhalten** festgehalten: der Runner-Test gibt `$PSVersionTable.PSVersion` und die Stimmenliste (Namen, keine Inhalte) im Testprotokoll aus.

## Lizenzausschluss (AGPL/GPL)
Kein AGPL/GPL beteiligt: Windows-Bestandteile bzw. (nicht verwendet) MIT. Kein Ausschlussgrund.

## Entscheidung
nicht nehmen

**Vorläufig, bis der Windows-Nachweis vorliegt** (Regel in `docs/INTEGRATIONS.md`: Windows-Evidenz erforderlich). Technische Hindernisse sind nicht bekannt. **Bedingungen für `nehmen`:**
1. Owner-Freigabe E8 für Teil B (Aufruf von `powershell.exe` mit `System.Speech`); kein Installationsbedarf.
2. **Runner-Test (windows-latest):** Synthese per `SetOutputToWaveFile` in eine temporäre WAV-Datei ergibt eine nicht leere Datei – oder der Test wird mit klarer Begründung **übersprungen** (keine Stimme); ein Skip zählt **nicht** als bestanden.
3. **Injektionstest** (Abschnitt „Sicherheitshinweise“ 2) und **Umlauttest** (3) bestanden; `-ExecutionPolicy` wird nicht benutzt (4).
4. **Notaus/Zeitlimit-Test:** laufender Prozessbaum wird beendet.
5. **Hörprobe am Windows-PC** des Besitzers (deutsche Stimme, Verständlichkeit) – manuell, im Rahmen der Abnahme; nicht automatisierbar.
Alternativen: `espeak-ng` (Zusatzinstallation, nicht Windows-Bordmittel), WinRT-Synthese (aufwendiger), Cloud-TTS (ausgeschlossen).

## Pruefung (Datum und Quelle)
2026-11-11, **nur Lesen** (keine Ausführung): Microsoft Learn – `System.Speech.Synthesis.SpeechSynthesizer` und Namespace-Seite (2026-07-01 / 2026-05-27), „What is Windows PowerShell“ (2025-11-20), `about_PowerShell_exe` (2025-09-29), `about_Execution_Policies` (7.6-Fassung, 2026-09-01), `Add-Type` (2026-06-16), `Console.InputEncoding` (2026-10-16), WinRT `SpeechSynthesizer` (2025-11-21); nuget.org `System.Speech` (2026-11-10, nicht verwendet); Repository-Code `src/jarvis/voice/system_tts.py`, `voice/factory.py`. Offen/nicht dokumentiert: Edition-Umfang von PowerShell 5.1, GAC-Status von `System.Speech`, Stimmen/Sprachpakete, stdin-als-Daten-Verhalten, Verhalten der Ausführungsrichtlinie bei `-Command`, Netznutzung der Stimmen.

## Umsetzungsstand Teil B (2026-11-12, WP05b)
**Freigaben:** E8 (PowerShell mit `System.Speech` als begrenzter TTS-Provider, Windows-Test), N1 (laufende Sprachausgabe bei Not-Aus stoppen), D3 (lange Texte in begrenzte Abschnitte), D4 (bei aktivem Not-Aus keine neue Ausgabe; nach Aufhebung keine alte Warteschlange).
**Umgesetzt:** `src/jarvis/voice/windows_tts.py` (`WindowsTTS`, Provider `windows`, **Standard bleibt `console`**).
- Fester Befehl `powershell.exe -NoProfile -NonInteractive -Command <fester Skripttext>`, `shell=False`; **kein** `-Command -`, kein `-ExecutionPolicy`. Der Text geht **nur als UTF-8-Bytes über die Standardeingabe**; das Skript liest die Bytes selbst (`OpenStandardInput` + `UTF8.GetString`, unabhängig von der Konsolenkodierung) und behandelt sie als Daten. Der Argumentaufbau erhält den Text nie (Strukturtest).
- Bereinigung (Steuer-/Formatzeichen entfernt, Leerraum vereinheitlicht), Gesamtlänge begrenzt (4 000 Zeichen), Aufteilung in Abschnitte von höchstens 500 Zeichen an Satzgrenzen (sonst Wortgrenzen); **ein Prozess je Aufruf, keine Warteschlange**. Zeitlimit abhängig von der Textlänge, höchstens 300 s.
- Fehler: PowerShell fehlt → `VoiceUnavailableError`; keine installierte Stimme (Exit-Code 3) → `VoiceUnavailableError`; sonst `TTSError` mit Exit-Code, **ohne Textinhalt und ohne Fehlerausgabe**.
- `stop()` beendet den Prozess (unter Windows samt Prozessbaum über ein Job-Object, falls verfügbar), ist idempotent und löst keinen Fehler aus; Abgebrochenes wird nie wiederholt.
- Not-Aus (`bootstrap.py`, additiv): `speech_guard` (nur Not-Aus) verhindert den Start einer neuen Ausgabe (ein fehlschlagender Guard sperrt ebenfalls); `voice_stopper` ist als Not-Aus-Komponente `voice` registriert und beendet eine laufende Ausgabe. Die PermissionEngine, der Not-Aus-Riegel und das Audit sind unverändert.
**Tests:** `tests/test_voice_windows_tts.py` (Fake-Prozess, Linux+Windows) und `tests/test_voice_windows_tts_real.py` (nur Windows: Synthese in WAV, Umlaute, Injektionstest mit Marker-Datei, Zeitlimit, `stop()`; ohne installierte Stimme wird begründet übersprungen – kein Nachweis).
**Entscheidung bleibt `nicht nehmen`**, bis der Windows-CI-Lauf (Runner-Test, soweit eine Stimme vorhanden ist) **und** die Hörprobe am Windows-PC des Besitzers vorliegen. Offen: Sprachqualität (SAPI-Stimmen, keine „natürlichen“ Stimmen), Zeit bis Ton (PowerShell-Start je Äußerung, **ungemessen**), Verhalten auf Windows 11 Home des Besitzers.
