# Phase 2 · Entscheidung zur Reset-Rückfrage

**Zur Entscheidung steht die enge Ausnahme für `confirm` in PR #264.** Sie erlaubt genau eine angebotene Antwort zu einer offenen Reset-Rückfrage. Der Entwurf basiert auf `main` bei `7cc65b0`. Das Nachrichtenformat bleibt v1.0. Die bisherigen GUI- und CLI-Einstiege nutzen weiterhin `PermissionEngine.reset_emergency_stop`. Die Standardoberfläche bleibt V1.

## Befund und Umsetzung

Auf der Basis verweigert der Fake während des Not-Aus jede Bestätigung. Der Controlleradapter erkennt den Reset an Werkzeug- und Aktionsnamen. Die Engine verwendet für gewöhnliche Rückfragen und für den Reset denselben synchronen Provider-Aufruf. Sie fragt beim Reset mit ausgeschalteter Sitzungsfreigabe und akzeptiert ausschließlich `ConfirmationChoice.ALLOW_ONCE`.

Der Entwurf bindet die Herkunft an die zwei im Repository zugelassenen Aufrufstellen in GUI und CLI. Unmittelbar um den vorhandenen Engine-Aufruf reserviert der Aufrufer den aktuellen UI-Provider. Nur in diesem Thread kann genau ein passender Provider-Rückruf die Reservierung beanspruchen. Anschließend veröffentlicht der Adapter eine eigene, undurchsichtige Rückfrage-ID. Die Engine-interne Kennung ist keine UI-ID. Der Fake modelliert denselben Vertrag mit eigenen Sitzungskennungen und einem intern gesetzten Rückfragetyp.

| Ereignis | Ergebnis |
| --- | --- |
| Reset ohne aktiven Not-Aus, erneute Anfrage bei bereits offener Rückfrage | Abgelehnt |
| Gewöhnliche Arbeit, fremde Sitzung, verbrauchte oder abgelaufene Rückfrage | Abgelehnt |
| Antwort `allow_session` auf passende Reset-Rückfrage | Abgelehnt, Rückfrage bleibt offen |
| Antwort `deny`, Fristablauf, Trennung der letzten Verbindung oder Serverende | Rückfrage geschlossen, Not-Aus bleibt aktiv |
| Zwei Antworten auf dieselbe ID | Nur die erste gültige Antwort schließt die Rückfrage |
| `allow_once` | Der Provider gibt die menschliche Wahl zurück. Die Engine entscheidet über die Aufhebung. Die UI wartet auf den gemeldeten Zustand. |

Die Grenzprüfung beim Antworten liest den Not-Aus-Zustand und prüft Frist und ID unter der Sperre des Adapters. Bei einem Anbieterwechsel oder einem Engine-Aufruf aus einem anderen Kontext fehlt die Reservierung. Während des Not-Aus schließt der Provider solche Rückfragen mit Ablehnung. Jede weitere programmgesteuerte Aufrufstelle, ein delegierender Provider oder eine künftig asynchrone Abfrage braucht einen eigenen Herkunftsnachweis. Für eine Änderung der Engine-Schnittstelle wäre eine gesonderte Freigabe erforderlich. Die bestehende prozessinterne Vertrauensgrenze für geladenen Python-Code gilt weiterhin.

## Tests

`tests/test_ui_reset_contract.py` prüft den Fake und den echten Controller über authentifizierte Loopback-POSTs. Der Gleichzeitigkeitstest startet zwei Antworten an einer gemeinsamen Barriere. Der Engine-Test hält nach angenommenem `allow_once` die Rückgabe des Providers an. In diesem Zeitfenster liegen ein positives Ack und ein aktiver Not-Aus gleichzeitig vor, und die echte Registry verweigert einen lokalen Echo-Aufruf. Nach Freigabe der Rückgabe wird die Aufhebung an der Engine und im Ereignisstrom geprüft. Ein weiterer Test prüft den vorhandenen CLI-Einstieg und eine konkurrierende gewöhnliche Provider-Rückfrage mit denselben Anzeigedaten.

Der Chromium-Test in `tests/test_control_center_e2e_browser.py` öffnet zwei Fenster mit demselben Reset-Dialog. Zuerst schließt ein Fenster, das zweite lehnt die Frage ab. Bei der nächsten Rückfrage schließt auch das letzte Fenster. Der Adapter meldet `cancelled` und die Engine bleibt gestoppt. QA-Ergebnisse für den jeweiligen Commit stehen in PR #264.

## Verträglichkeit mit PR #263

Verglichen wurden die Git-Bäume von #263 (`e7bcd496`) mit den 40 weiteren offenen PR-Köpfen am 20. November 2026. `git merge-tree --write-tree --name-only` berechnet das Ergebnis ohne Branchänderung. Ein zweiter Vergleich jedes Kopfes mit `main` trennt bereits bestehende Konflikte ab.

| Vergleich | Ergebnis |
| --- | --- |
| #263 mit main | GitHub meldet zusammenführbar. |
| #255 `bf1aa6d0`, #256 `cab16334`, #258 `c1a97154`, #261 `4d33fc95` | Textkonflikt in `tests/test_control_center_e2e_browser.py`. Bei einer späteren Integration beide Testsammlungen erhalten. |
| #259 `3b9b100b` | Zusätzlich Konflikt in `control_center/launcher.py`. Beim späteren Abgleich müssen die Opt-in-Serverauswahl von #263 und die Agenten- und Missionsansichten aus #259 gemeinsam verdrahtet werden. |
| #251 `2c4de4ef` | Automatische Textzusammenführung möglich. Die parallelen GET-Ansichten für Agenten und Trace gehen über die Schnittstellen von main hinaus. |
| #85, #72, #26 | Dieselben Konfliktdateien wie gegenüber main, in Automatisierung oder Dokumentation. |
| Übrige geprüfte Köpfe | Kein Textkonflikt. |

Das Nachrichtenformat für `confirm` und die bestehende SSE-Verbindung können weiterverwendet werden. #263 verwendet für seine HTML-Erweiterungen konkrete Einfügestellen der V1-Seite. Die Stellen sind auch in den geprüften V2-Seiten vorhanden. Die V2.1-Missionsansicht und die V2-Agentenansichten sind auf main noch nicht verfügbar. Der Vergleich ist eine Prüfung der Quellstände. Ein kombinierter Lauf der konfliktbehafteten Zweige steht aus.

## Abnahmestand

| Stufe | Status |
| --- | --- |
| Technisch implementiert | Vertragsentwurf, beide Adapter und isolierte Regressionstests auf dem Reviewbranch. Änderungen an PermissionEngine, EmergencyStop und ToolRegistry sind nicht Bestandteil des Diffs. |
| Automatisiert getestet | Tests gegen reale Engine und Registry, den Fake sowie zwei Chromium-Fenster. Plattform- und Skip-Angaben stehen im PR-Bericht. |
| Auf realer Windows-Hardware geprüft | Offen, einschließlich V1-Abnahme #186. |
| Produktiv freigegeben | Offen. Der Besitzer entscheidet über den Vertragsentwurf. Weitere schreibende NEXUS-Phasen beginnen erst nach ihrer jeweiligen Freigabe. |
