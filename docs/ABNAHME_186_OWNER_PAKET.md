# #186 – Owner-Paket (Stand 2026-11-18) und Manifest-Review

## 1. Offene Handtests in drei Blöcken
Reihenfolge sicher: erst NEXUS-Fenster, dann Sprache, zuletzt UAC. Keine Aktion bestätigt Claude für dich.

**Block A – NEXUS (Browser, ca. 5 Min.)**
1. B9-3d: Befehl `Erstelle die Datei b93d_retry.txt mit dem Inhalt: test`; bei offener Frage im Konsolenfenster von NEXUS Strg+C. Erwartet: Datei fehlt, Audit `confirmation_rejected`.
2. B9-4: NOTAUS in Dashboard, Orb und Overlay; danach Auftrag senden (muss verweigert werden); danach Aufheben/Reset und Auftrag (muss wieder gehen). Frage zum Reset: erwartetes Verhalten laut Matrix S8b.
3. S9: nach Abbruch `/resume` im neuen NEXUS: unterbrochenes Ziel wird angeboten, nichts läuft ohne neue Freigabe.

**Block B – Sprache (Mikrofon, ca. 5 Min.)**: S2a/b/c, S3a, S4, S8a laut `docs/ABNAHME_186_COMPUTERUSE_UND_HANDTESTS.md`.

**Block C – UAC (nur Owner)**: S6.

## 2. Manifest-Blocker (pr-tests, `test_protected_files`)
Ursache: Die vom Owner genehmigte Erweiterung des UI-Vertrags (`steps`, Commit 858eff0) änderte zwei geschützte Dateien:
- `src/jarvis/ui_contract/schema.py`: `ACTIVITY_ITEM` + optionales Feld `"steps": Num(0, 200)`.
- `src/jarvis/ui_contract/schema/ui-events.schema.json`: generiert, gleiche Ergänzung (`minimum 0`, `maximum 200`, `number`).
Nichts an Berechtigungen, X0 oder Not-Aus geändert. Das Feld ist optional (alte Clients unberührt).

Review-Schritte für den Owner:
1. `git diff 04fd87b 194562f -- src/jarvis/ui_contract` lesen (7 Zeilen).
2. Nur bei Zustimmung: `python -m tests.support.protected_manifest --write --confirm-owner-review`, danach `git diff tests/support/protected_manifest.json` (nur diese zwei Hashes dürfen sich ändern), Commit durch den Owner.
Stand lokaler Hashes (SHA-256, Anfang): schema.py 5ab317fccaa0b311, ui-events.schema.json 96feca3c14824cbf.
Claude hat das Manifest NICHT geändert.

## 3. CI-Stand (API, Abfrage 2026-11-18)
- 858eff0: tests success, GUI E2E success, uia-compat success, **pr-tests failure** (tests-linux und tests-windows beide failure; Linux belegt = Manifest, Windows-Grund nicht einzeln geprüft).
- 194562f: GUI E2E success (native-desktop, browser-e2e win/linux); pr-tests und uia-compat dafür nicht gestartet (Owner startet sie manuell). Windows-Nachweis für 194562f steht damit aus.
