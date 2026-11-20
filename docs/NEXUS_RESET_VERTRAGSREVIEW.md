# NEXUS Ultimate · Entscheidungsvorlage zum Not-Aus-Reset

Status: Review angefordert. Basis: main `7cc65b0e9fcda545f784d887e71c28a279669b04`. Die optionale Leseansicht ist als separater Entwurf in #263 implementiert. Dieses Dokument ändert weder den UI-Vertrag noch eine Sicherheitsentscheidung.

## Zu entscheidende Frage

Soll der v1-Vertrag während eines aktiven Not-Aus das Beantworten genau der bereits offenen, von der Engine gestellten Reset-Rückfrage erlauben? Derzeit beschreibt `docs/UI_CONTRACT.md` im Abschnitt zum echten Backend die Abweichung und verweist sie auf eine Besitzerentscheidung.

## Beobachtung auf dem isolierten Linux-Testsystem

Beide Adapter wurden getrennt an einen echten Loopback-Control-Center-Server gebunden. Die reale Variante verwendete einen frischen Test-Workspace und den regulären Controlleradapter. Nach bestätigtem Not-Aus wurde über den vorhandenen Befehlspfad ein Reset angefragt. Anschließend wurde die tatsächlich zurückgelieferte Reset-Rückfrage mit `deny` beantwortet.

| Befund | FakeUiBackend | ControllerUiBackend |
| --- | --- | --- |
| Reset anfragen | ok, confirmation_requested | ok, confirmation_requested |
| Ablehnung für die passende offene Anfrage | ok=false, emergency | ok=true, ok |
| Not-Aus nach der Ablehnung | aktiv | aktiv |

`ui_contract/fake.py::_refuse_in_emergency` sperrt auch diese Antwort. `interface/ui_events.py::_is_reset_answer` unterscheidet die bereits offene Reset-Rückfrage. `tests/test_ui_event_bus.py::test_reset_emergency_is_only_a_request_and_the_human_decides` prüft die enge Ausnahme im Adapter. Der Test `tests/test_control_center_web.py::test_emergency_button_sends_only_the_contract_command` schützt die bestehende Weboberfläche vor einem zusätzlichen Reset-Befehl.

## Umfang eines späteren freizugebenden Vertrags-PR

1. Besitzer legt die normative Semantik für beide Adapter fest. Bei Beibehaltung des derzeit strengeren Testvertrags bleibt ein Premium-Reset-Bedienelement aus.
2. Bei Freigabe der engen Ausnahme die angebotenen Antworten auf eine konkrete offene Engine-Rückfrage begrenzen. Veraltete fremde IDs, wiederholte Entscheidungen, gewöhnliche Rückfragen und neue Arbeitsaufträge müssen während des Not-Aus weiterhin scheitern.
3. Beide Adapter gegen dieselben Fälle prüfen. Ergänzend sind Timeout, letztes getrenntes Fenster, zwei konkurrierende Antworten und der weiterhin wirksame Tool-Stopp zu testen.
4. Ein positiver Ack für die Reset-Anfrage darf die Anzeige nicht auf betriebsbereit setzen. Maßgeblich ist der durch die Engine bestätigte Zustand.

Dieser Entscheidungsstand hat keine Produktivfreigabe. Das Fenster-, Geräte- und Wiederanlaufverhalten muss im Rahmen der offenen V1- und NEXUS-Windows-Prüfungen separat abgenommen werden.
