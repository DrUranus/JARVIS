# V2: Lizenzprüfung für ausschließlich private, nicht gewerbliche Nutzung

**Status: Dokumentation, keine Rechtsberatung.** Besitzerentscheidung: JARVIS V2 wird vorerst **ausschließlich privat und nicht gewerblich** genutzt. Geprüft wurden die Lizenztexte und Herstellerseiten, soweit lesbar (Stand 2026-11-11). Es wurde nichts installiert oder übernommen; jede Übernahme fremden Codes braucht weiterhin Lizenz-, Sicherheits- und Kompatibilitätsprüfung und eine separate Freigabe. Sicherheitsgrenzen und Freigabebeschränkungen bleiben unverändert. Bei Rechtsfragen entscheidet der Wortlaut des jeweiligen Vertrags bzw. eine schriftliche Auskunft des Herstellers, nicht diese Zusammenfassung.

**Kennzeichnung:** *wörtlich* = aus dem Vertrags-/Lizenztext. *Zusammenfassung* = nur aus einer Modellzusammenfassung der Seite (nicht wörtlich geprüft). *nicht dokumentiert* = auf den gelesenen Seiten nicht gefunden.

## 1. Docker Desktop (relevantester Fall)
Quelle: Docker Subscription Service Agreement, „Last updated on August 26, 2026“; `docs.docker.com/subscription/desktop-license/` (ohne Datum). Der Vertrag enthält **keinen eigenen Docker-Desktop-Lizenztext**; die Docs-Seite sagt, Desktop sei darunter lizenziert. Der Vertrag wurde zu rund 57 % wörtlich gelesen (Abschnitte 1 bis 6.6), der Rest nur als Zusammenfassung.

### 1.1 Was der Text für private Nutzung sagt
| Stelle | Inhalt | Bedeutung für JARVIS (privat) |
|---|---|---|
| §3.2 (wörtlich) | „Personal“-Abonnements sind „intended for individual, non-institutional use“ | passt zu privater Einzelnutzung |
| §3.2(a) „Developer Use“ (wörtlich) | „limited to a single, individual developer acting in a personal, non-commercial capacity to develop Open Source Software or free applications“; **nicht** „in connection with an individual's employment or engagement by a company, organization, or institution … whether paid or unpaid“ | nichtkommerziell: ja. **Zweck-Bedingung:** Entwicklung von quelloffener Software **oder „free applications“** |
| §1 (wörtlich) | „Open Source Software“ = fremde Software, die als „free software“, „open source software“ o. ä. verbreitet wird | JARVIS hat laut Repository **keine Lizenzdatei und keine Lizenzangabe** in `pyproject.toml`/README (Prüfung 2026-11-11) und ist damit nach außen **nicht als quelloffen lizenziert**. Ob das Repository öffentlich ist, wurde nicht geprüft. |
| „free applications“ | **nicht definiert** | Ob ein privates, nicht veröffentlichtes Assistenzsystem eine „free application“ ist, bleibt **offen** (Auslegung) |
| §3.3 (wörtlich) | Nutzung von Docker Desktop **ohne** bezahltes Abonnement ist beschränkt auf „(i) … a non-commercial open source project and/or (ii) … a commercial undertaking with fewer than 250 employees and less than US $10,000,000 … in annual revenue“; Behörden nie ohne Abonnement | Dieser Satz nennt „Personal use“ **nicht**; die Docs-Seite dagegen nennt „Personal use“ als kostenlos. Die beiden Texte sind nicht deckungsgleich. |
| Docs-Seite (Paraphrase) | kostenlos: Kleinunternehmen (unter 250 Beschäftigte **und** unter 10 Mio. US-$), Personal use, Bildung, nicht kommerzielle Open-Source-Projekte; bezahlt: Großorganisationen, Behörden, „commercial use beyond the free tier limits“ | „Personal use“ wird nicht definiert |
| Docker-Installationsseite | formuliert die Schwelle teils mit „OR“ statt „AND“ | Abweichung; maßgeblich ist der Vertragstext (UND) |
| §3.2 (wörtlich) | „Docker reserves the right to audit usage patterns and to determine whether any use under the Personal Service Subscriptions is allowed and to require migration to an appropriate paid Subscription upon notice.“ | Docker kann prüfen und Wechsel auf ein bezahltes Abonnement verlangen |
| §2.1 (wörtlich) | „Users require a Docker Hub account to access and use the Service“ | ob für den kostenlosen Desktop-Betrieb ein Konto nötig ist: **nicht dokumentiert**; Konto bedeutet Datenweitergabe an Docker |
| §1/§2.1 (wörtlich) | „Docker owns the Usage Data …“ (Nutzungsdaten gehören Docker, auch zur Verbesserung der Dienste, aggregiert und de-identifiziert) | Nutzungsdaten fließen an Docker; spezielle Desktop-Telemetrie: **nicht dokumentiert** |
| §18.4 (Zusammenfassung) | Docker darf die Bedingungen ändern (Mitteilung oder Veröffentlichung); Frist **nicht dokumentiert** | Bedingungen können sich ändern |
| §4.5 (wörtlich) | Daten kostenloser Konten können nach Beendigung innerhalb von 30 Tagen gelöscht werden | |

### 1.2 Bewertung (Einschätzung, kein Rechtsurteil)
- **Privat und nichtkommerziell ist die Grundvoraussetzung erfüllt.** Zweifel bleiben bei der **Zweckbedingung** („Open Source Software or free applications“) und beim **undefinierten Begriff „Personal use“**; die Docs-Seite spricht für, der Vertragstext nicht eindeutig für die Zulässigkeit eines privaten, nicht quelloffenen Projekts.
- **Eindeutiger wäre:** JARVIS unter einer Open-Source-Lizenz zu veröffentlichen (Entscheidung des Besitzers, nicht Teil dieser Vorlage) **oder** eine schriftliche Bestätigung von Docker einzuholen (Kontaktweg: nur Vertrieb, `docker.com/pricing/contact-sales/`; eine eigene Lizenz-Adresse ist **nicht dokumentiert**) **oder** auf Alternativen auszuweichen (Abschnitt 3).
- **Risiko bei Zweifel:** nach dem Text Aufforderung zum Wechsel auf ein bezahltes Abonnement „upon notice“; eine rückwirkende Zahlung ist **nicht dokumentiert**.

### 1.3 Einschränkungen bei späterer gewerblicher Nutzung
- **Kleines Unternehmen:** kostenlos nach §3.3(ii) nur bei **weniger als 250 Beschäftigten und weniger als 10 Mio. US-$ Jahresumsatz**. „Commercial undertaking“ ist **nicht definiert**; ob Freiberufler/Einzelunternehmer dazugehören, ist **nicht dokumentiert**.
- **Nicht über das private Konto:** §5.1(8) (wörtlich) verbietet, „no-Fee accounts“ zu nutzen, um Dienste für einen Arbeitgeber oder ein Unternehmen zu erbringen oder zu empfangen; „Developer Use“ schließt Nutzung im Zusammenhang mit Anstellung/Beauftragung durch ein Unternehmen ausdrücklich aus.
- **Behörden** immer bezahlt; **Großunternehmen** (≥ 250 oder ≥ 10 Mio. US-$, gemäß Vertrag beide Schwellen) bezahlt.
- Jeder gewerbliche Einsatz (auch Auftragsarbeit oder Weitergabe der Ergebnisse gegen Entgelt) vorher **schriftlich klären** und das Abonnement bzw. die Alternative **vor** dem Einsatz sichern.

## 2. Open-Source-Komponenten im Vergleich
Gilt für den rein privaten Einsatz ohne Weitergabe. `docs/INTEGRATIONS.md` schließt (A)GPL-Abhängigkeiten ohnehin aus; die Tabelle zeigt die Lage, falls eine Komponente später doch betrachtet wird.

| Komponente | Lizenz | Quelle/Stand | Privat, nichtkommerziell | Einschränkung bei späterer gewerblicher Nutzung |
|---|---|---|---|---|
| OpenHands (Haupt-Repo) | MIT | `LICENSE` gelesen (Copyright 2025) | ja | keine besondere; Lizenzhinweis beibehalten |
| OpenHands `software-agent-sdk` | MIT | `LICENSE` gelesen (Copyright 2026); `clients/typescript/LICENSE` nicht gelesen | ja | wie oben |
| OpenHands Abhängigkeiten (415 im Lock) | **nicht geprüft** | `uv.lock` | offen | **Lizenzprüfung Pflicht** vor Übernahme (u. a. `litellm`, `browser-use`, `lmnr`, `posthog`, Chromium) |
| Docker Desktop | Docker-Abonnementvertrag | Abschnitt 1 | wahrscheinlich, Zweifel bei Zweckbedingung | Abschnitt 1.3 |
| Docker Engine (`docker-ce`) | Apache-2.0 laut Installationsseite | `docs.docker.com/engine/install/` | ja | keine Abonnementpflicht, soweit direkt installiert; **ausdrückliche Aussage zu WSL-2-Installation nicht dokumentiert**; „Commercial use of Docker Engine obtained via Docker Desktop“ in größeren Unternehmen bezahlpflichtig |
| Podman Desktop | Apache-2.0 | `LICENSE` gelesen | ja | keine besondere |
| Rancher Desktop | Apache-2.0 | `LICENSE` gelesen | ja | keine besondere |
| VirtualBox (Basis) | GPLv3 | Downloads/Licensing-FAQ | ja | Nutzung ohne Weitergabe unkritisch; Weitergabe von Kopien/Änderungen unterliegt GPL |
| VirtualBox Extension Pack | PUEL | Licensing-FAQ | **kostenlos nur für persönlichen und Bildungszweck** (laut FAQ; Test-/Evaluierungsnutzung nicht mehr abgedeckt) | **kommerziell kostenpflichtig**; Funktionen wanderten laut Changelog 7.2.6 teils in das freie Basispaket |
| VMware Workstation | kostenlos für alle (Ankündigung 2024-11-11); aktuelle Lizenzseite nicht abrufbar (Broadcom 404) | Blogbeitrag | ja | **Lizenztext nicht gelesen**; kommerzielle Nutzung laut Ankündigung kostenlos, aber ohne Support; vor Einsatz Lizenztext prüfen |
| QEMU | GPLv2 | `qemu.org` | ja | wie GPL |
| WSL 2 | Teil von Windows | Microsoft-Dokumentation | ja | untersteht der Windows-Lizenz; **Windows-Lizenztext nicht gelesen** |
| pypdf | BSD-3-Clause | `docs/integrations/pypdf.md` | ja | keine besondere |
| MCP-SDK `mcp` | MIT | `docs/integrations/mcp.md` | ja | keine besondere |

## 3. Empfehlung für den privaten Betrieb
1. **Container-Prototyp:** Wenn Docker Desktop genutzt wird, vorher die Zweckbedingung klären (schriftliche Auskunft oder JARVIS als Open Source lizenzieren). Alternative ohne Abonnementfrage: **Rancher Desktop** (Apache-2.0, Windows 11 Home ausdrücklich genannt) oder **Podman Desktop**; beide wären nach `docs/INTEGRATIONS.md` zu prüfen (Pflege, Sicherheitsstatus, Hash, Windows-CI) und sind **nicht freigegeben**.
2. **VM-Variante:** VMware Workstation (kostenlos) oder VirtualBox ohne Extension Pack (GPLv3, kostenlos); Extension Pack nur privat.
3. **Bei jeder Variante:** keine Installation vor Klärung und Freigabe; Windows-Home-Eignung und Isolation bleiben die Kriterien aus `docs/V2_SANDBOX_VORSCHLAG.md`.
4. **Dokumentationspflicht:** Wird später gewerblich genutzt, ist diese Tabelle neu zu prüfen und die Lizenzlage **vor dem ersten gewerblichen Einsatz** zu klären (Abschnitt 1.3).

## 4. Offene Punkte
- Zweckbedingung („free applications“) und Begriff „Personal use“ bei Docker; schriftliche Auskunft des Besitzers an Docker bzw. Open-Source-Lizenzierung von JARVIS (Entscheidung des Besitzers).
- Vertragsabschnitte ab 6.6 des Docker-Vertrags (u. a. 9, 17, 18) nur als Zusammenfassung gelesen; Product Schedule PDF, Terms of Use und DPA nicht gelesen.
- VMware-Lizenztext, Windows-Lizenz für WSL, Chromium und die 415 OpenHands-Abhängigkeiten nicht geprüft.
