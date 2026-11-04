# Recherche-Agent: Textextraktion (trafilatura) und Suchquellen (Brave Search API, SearXNG, Google, Bing, Mojeek)

Pruefbericht nach `docs/INTEGRATIONS.md`, Schritt `research-vetting`. Geprueft wurde nur an offiziellen Quellen (Projekt-Repositories und LICENSE-Dateien, PyPI-Seiten bzw. PyPI-JSON, Dokumentations- und Preisseiten der Anbieter, Advisories-Seiten). Es wurde **nichts installiert, kein Code geschrieben, nichts heruntergeladen ausser Metadaten und Textseiten**. Das Abrufwerkzeug fasst HTML-Seiten teils zusammen; PyPI-JSON und Rohdateien von GitHub wurden im Volltext gelesen. Alles, was nicht belegt werden konnte, steht als "nicht belegt" oder "offen". Es wurde keine Angabe aus dem Gedaechtnis uebernommen. Der Pruefstand ist **2026-11-04**.

## Name und Zweck
Der heutige Research-Agent (`src/jarvis/research/`, README Abschnitt "Business / Research / Finance v1") liest nur **vorgegebene URLs** ueber das `browser`-Tool und extrahiert mit eigenen Regeln (`research/extract.py`, ohne LLM) Passagen und Zahlen aus dem Seitentext. Er **sucht nicht** (`config/jarvis.toml`: "It reads the URLs it is given; it does not search the web."). Ein spaeterer Ausbau braucht (a) eine **Suchquelle**, die zu einer Anfrage URLs liefert, und (b) eine bessere **Textextraktion** aus HTML. Geprueft werden:

| Kandidat | Art | Projekt |
|---|---|---|
| **trafilatura** | Python-Bibliothek, Hauptinhalt aus HTML | https://github.com/adbar/trafilatura, https://pypi.org/project/trafilatura/ |
| **Brave Search API** | bezahlter Webdienst (HTTPS), kein Paket | https://brave.com/search/api/ |
| **SearXNG** | selbst betriebene Metasuchmaschine, **nur als getrennter Prozess** | https://github.com/searxng/searxng |
| **Google Custom Search JSON API** | Webdienst | https://developers.google.com/custom-search/v1/overview |
| **Bing Search APIs** | Webdienst (eingestellt) | https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement |
| **Mojeek Search API** | bezahlter Webdienst | https://www.mojeek.com/services/search/web-search-api/ |

Nicht geprueft (keine offizielle Suchschnittstelle belegt, daher kein Kandidat): DuckDuckGo, Startpage und Scraping beliebiger Suchseiten. Scraping der HTML-Trefferseiten eines Anbieters ohne API wird **nicht** empfohlen (siehe Nutzungsbedingungen unten; deren Wortlaut fuer diese Anbieter wurde nicht gelesen: offen).

**Bestehende HTTP-Schicht (Befund im Repository, Stand `main` 4c28988):** Die einzige HTTP-Stelle im Produktionscode ist `src/jarvis/voice/openai_provider.py` (`urllib.request`, Zeitlimit, HTTPS-Endpunkt aus der Konfiguration, kein Fremdpaket). Der Research-Agent holt Seiten **nicht** selbst, sondern ueber das `browser`-Tool (jede Navigation prueft `BrowserController` und `PermissionEngine`; `research/urls.py` verwirft Nicht-http(s), Zugangsdaten in der URL und private/Loopback-Adressen, DNS wird nicht aufgeloest). Eine Suchanfrage an einen Anbieter waere dagegen ein **Netzwerkzugriff des JARVIS-Prozesses** und muesste als eigenes Tool ueber `ToolRegistry.execute` -> `PermissionEngine` laufen (neue Ressource, Standard aus, Rueckfrage); die Verdrahtung nur in `src/jarvis/bootstrap.py`. Fuer die Brave-API genuegt `urllib.request` wie im STT-Cloud-Provider: **keine neue Abhaengigkeit noetig**. trafilatura wuerde nur auf bereits geladenen Text angewandt (`extract(html)`), nicht zum Laden (`fetch_url` bliebe ungenutzt).

Ergebnis ist **nur dieses Dokument**. Jeder Einbau ist ein eigener, vom Besitzer freizugebender Schritt.

## Lizenz (Wortlaut)
Gepruefter Tag: 2026-11-04.

**trafilatura: Apache-2.0.** > "Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/" (Fundstelle: https://raw.githubusercontent.com/adbar/trafilatura/master/LICENSE). PyPI 2.3.1: `license_expression` "Apache-2.0". README: > "This package is distributed under the Apache 2.0 license. Versions prior to v1.8.0 are under GPLv3+ license." (README, Abschnitt "License"). Fruehe Versionen sind also GPL; es darf nur die gepruefte Version (>= 1.8.0, hier 2.3.1) gepinnt werden.

**SearXNG: AGPL-3.0.** > "GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007" (Fundstelle: https://raw.githubusercontent.com/searxng/searxng/master/LICENSE; README: "This project is licensed under the GNU Affero General Public License (AGPL-3.0)."). Das ist nach `docs/INTEGRATIONS.md` **ausgeschlossen als Bibliothek oder eingebundener Code**. Zulaessig waere es nur als **getrennter Prozess ohne Einbindung** (siehe Abschnitt "Lizenzausschluss (AGPL/GPL)").

**Brave Search API, Google Custom Search, Bing, Mojeek:** Dienste mit Vertrag, keine Open-Source-Lizenz. Massgeblich sind die Nutzungsbedingungen:
- Brave: > "use the API and Documentation solely to develop, test, and integrate the API with, the Customer Applications" (§3(a)(i)); verboten ist > "store, cache, or create a database of Search Results, in whole or in part, other than transient storage" (§3(b)(i)), > "redistribute, resell, or sublicense the Search Results" (§3(b)(xii)), > "circumvent or bypass rate limits or service limits through any method" (§3(b)(v)) sowie die Nutzung der Ergebnisse > "to create, evaluate, train, re-train, fine-tune, benchmark" (§3(b)(xiii), der Satz im Abruf ist gekuerzt: vollstaendiger Gegenstand der Klausel nicht im Wortlaut gelesen, siehe offene Fragen). Anbieter: > "Brave Software, Inc., a Delaware corporation" (§1), kalifornisches Recht (§14(j)). Fundstelle: https://api-dashboard.search.brave.com/terms-of-service. Die FAQ der Produktseite sagt: Speichern oder Training sei erlaubt > "with a plan that includes storage rights" (https://brave.com/search/api/), welche Tarife das sind, steht auf der Preisseite der Dokumentation, deren Inhalt im Abruf **leer** war: nicht belegt.
- Mojeek (Startup-Tarif): > "Do not compile, copy, or store any Data." / > "Do not cache any Data, except to temporarily cache in order to serve the same user for up to 1 hour." / > "Do not use Data as part of any search index." / > "All data provided by the Services ("Data") may be used in internet search experiences." (https://www.mojeek.com/about/legal/api-terms.html). Zu KI-/LLM-Nutzung schweigt dieser Vertrag; die Produktseite nennt "AI Usage" als Tarifmerkmal ohne Bedingungen (https://www.mojeek.com/services/search/web-search-api/): **widerspruechlich/unklar**. Englisches Recht, Gerichte von England und Wales.
- Google: > "This API is not available for new customers." (https://developers.google.com/custom-search/v1/overview). Eigene Nutzungsbedingungen: nicht gelesen.
- Bing: > "Bing Search APIs will be retired on August 11, 2025. Any existing instances of Bing Search APIs will be decommissioned completely, and the product will no longer be available to be used or new customer signup." (https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement). Als Ersatz nennt Microsoft "Grounding with Bing Search as part of Azure AI Agents" (an Azure-KI-Agenten gebunden, nicht geprueft).

## Version und Datum
Stand PyPI 2026-11-04 (Zeitstempel UTC):

| Paket | Version | veroeffentlicht |
|---|---|---|
| trafilatura | 2.3.1 | 2026-10-06 (Wheel `py3-none-any`, 158 660 Byte) |
| trafilatura | 2.3.0 / 2.2.0 / 2.1.0 / 2.0.0 | 2026-10-02 / 2026-07-31 / 2026-06-07 / 2024-12-03 |
| lxml | 6.1.3 | 2026-09-02 |
| certifi | 2026.10.23 | 2026-10-23 |
| courlan | 1.4.0 | 2026-06-01 |
| htmldate | 1.11.0 | 2026-10-02 |
| justext | 3.0.2 | 2025-02-25 |

Die Dienste haben keine Version; Preise und Bedingungen mit Abrufdatum 2026-11-04 stehen unter "Pflege" und "Datenabfluss". SearXNG: GitHub-Seite 9 861 Commits, **keine Release-Angabe** auf der Hauptseite (Tags verlinkt, nicht gelesen); es gibt kein PyPI-Paket, das hier geprueft wurde: Version fuer einen Einbau **unbekannt**.

## Pflege
- **trafilatura:** Repository oeffentlich, nicht archiviert, 1 729 Commits, 54 offene Issues (GitHub, 2026-11-04). Sechs PyPI-Veroeffentlichungen seit Juni 2026; zwischen 2.0.0 (2024-12-03) und 2.1.0 (2026-06-07) lag eine Pause von rund 18 Monaten. Die GitHub-Releases-Liste ist leer (die Versionen stehen nur auf PyPI). Entwicklungsstatus-Klassifikator "5 - Production/Stable".
- **Sicherheitsmeldungen trafilatura:** > "There aren't any published security advisories." (https://github.com/adbar/trafilatura/security/advisories); eine "Security policy" ist verlinkt, ihr Inhalt wurde nicht gelesen. Das ist keine Aussage ueber fehlende Schwachstellen. CVE-Datenbanken wurden nicht durchsucht (keine offizielle Projektquelle). Fuer die transitiven Pakete (lxml, urllib3, certifi usw.) wurden die Advisories-Seiten **nicht** gelesen: offen.
- **SearXNG:** nicht archiviert, aktiv (9 861 Commits). Advisories: > "There aren't any published security advisories." (https://github.com/searxng/searxng/security/advisories).
- **Brave Search API:** kommerzieller Dienst; Dienst-Ende oder Laufzeit nicht angegeben. **Kosten:** > "Search: $5 per 1,000 requests. Includes $5 in free credits every month." (https://brave.com/search/api/); derselbe Kopf nennt > "Up to $20 in free calls every month · Prepaid credits, no subscription." Die Seite erklaert die Abweichung ($5 gegen $20) nicht: **Widerspruch, nicht aufgeloest**. Eine Kreditkarte wird verlangt (FAQ-Frage "Why do you ask for a credit card?", Antwort nicht gelesen). **Rate-Limit:** Produktseite: "50 queries per second" fuer Search; Dokumentation: 1-Sekunden-Gleitfenster, bei Ueberschreitung HTTP 429, fehlgeschlagene Anfragen werden nicht berechnet (https://api-dashboard.search.brave.com/documentation/guides/rate-limiting); dort steht ein Beispiel mit 1 Anfrage/s und 15 000/Monat, ob das ein Tarif oder nur ein Beispiel ist, ist nicht gesagt.
- **Google Custom Search JSON API:** > "Custom Search JSON API provides 100 search queries per day for free." / > "Additional requests cost $5 per 1000 queries, up to 10k queries per day." / > "Existing Custom Search JSON API customers have until January 1, 2027 to transition to an alternative solution." Fuer **neue Kunden nicht verfuegbar**, endet 2027-01-01: **ausgeschlossen**.
- **Bing Search APIs:** am 2025-08-11 eingestellt: **ausgeschlossen**.
- **Mojeek:** Preise laut Produktseite: Startup "£2 per 1,000 requests" (5 Anfragen/s, 100 000/Tag), Business "£3 per 1,000 requests" (10/s, 400 000/Tag), Enterprise auf Anfrage; kostenloses Startguthaben im Startup-Tarif, Bankkarte noetig. (Eine Suchmaschinen-Zusammenfassung nannte "£1 CPM Personal"; das steht **nicht** auf der gelesenen offiziellen Seite und wird nicht uebernommen.) Speichern: nur Business/Enterprise ("indefinite data retention"), Startup: Cache hoechstens eine Stunde.

## Python- und Windows-Kompatibilitaet
Projekt verlangt Python >= 3.11 und Windows als Zielsystem. Ein Linux-Lauf ist kein Windows-Nachweis; hier lief **kein** Code, alle Angaben stammen aus Registerdaten (PyPI).
- **trafilatura 2.3.1:** `requires_python >=3.10`; Klassifikatoren 3.10 bis 3.15, "Operating System :: Microsoft"; reine Python-Wheel `py3-none-any`. Windows-Eignung haengt an den Abhaengigkeiten:
  - **lxml 6.1.3:** Wheel `cp311-cp311-win_amd64` vorhanden (4 032 700 Byte).
  - **charset-normalizer 3.5.2:** Wheel `cp311-cp311-win_amd64` und `cp37-abi3-win_amd64` vorhanden.
  - **regex 2026.9.29** (ueber dateparser): Wheel `cp311-cp311-win_amd64` vorhanden.
  - Alle anderen Pakete der Kette sind reine Python-Wheels (`py3-none-any`/`py2.py3-none-any`).
- **Windows-Nachweis steht aus.** Weder Installation noch Import wurden ausgefuehrt; ein Lauf im CI-Windows-Job (`tests.yml`) waere Teil eines Folgeschritts.
- **Gewicht:** `babel` (Abhaengigkeit von courlan) ist ein Wheel von 10,2 MB (Locale-Daten); die Kette hat rund 19 Pakete.
- **SearXNG:** die Installationsseite nennt "Installation container", "Installation Script" und "Step by step installation" und macht **keine Aussage zu Windows** (https://docs.searxng.org/admin/installation.html). Betrieb waere ein Container (Docker Desktop mit WSL/Linux-VM) oder ein Linux-Rechner im Heimnetz: nicht belegt, ob es unter Windows direkt laeuft.
- **Brave/Mojeek:** reine HTTPS-Dienste, plattformunabhaengig; Windows-Nachweis nur ueber den spaeteren CI-Lauf des Client-Codes.

## Transitive Abhaengigkeiten
Stand PyPI-JSON 2026-11-04 (nur Laufzeit, keine Extras; Lizenzfeld laut PyPI, die LICENSE-Dateien der transitiven Pakete wurden mit Ausnahme der Kopfzeilen **nicht** einzeln gelesen).

**trafilatura 2.3.1** verlangt: `certifi`, `charset_normalizer>=3.5.2`, `courlan>=1.4.0`, `htmldate>=1.11.0`, `justext>=3.0.2`, `lxml>=6.1.3`, `urllib3<3,>=2.8.0`.

| Paket | gepruefte Version | Lizenz laut PyPI | weitere Abhaengigkeiten |
|---|---|---|---|
| certifi | 2026.10.23 | **MPL-2.0** | keine |
| charset-normalizer | 3.5.2 | MIT (LICENSE: "MIT License / Copyright (c) 2025 TAHRI Ahmed R.") | keine |
| courlan | 1.4.0 | Apache-2.0 | babel, tld, urllib3 |
| babel | 2.18.0 | BSD-3-Clause | keine (pytz nur fuer Python < 3.9) |
| tld | 0.13.2 | **"MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later"** | keine |
| urllib3 | 2.8.0 | MIT | keine |
| htmldate | 1.11.0 | Apache-2.0 | charset_normalizer, dateparser, lxml, python-dateutil, urllib3 |
| dateparser | 1.5.0 | BSD-3-Clause | python-dateutil, pytz, regex, tzlocal |
| python-dateutil | 4.0.0 | BSD-3-Clause | tzdata |
| pytz | 2026.6 | MIT | keine |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | keine |
| tzlocal | 5.4.5 | MIT | tzdata (nur Windows) |
| tzdata | 2026.6 | Apache-2.0 | keine |
| lxml | 6.1.3 | BSD-3-Clause (nativ, buendelt libxml2/libxslt: Lizenz der gebuendelten Teile nicht gelesen: offen) | keine |
| justext | 3.0.2 | BSD-2-Clause | `lxml[html_clean]` (-> lxml-html-clean 0.4.6, BSD-3-Clause) |

Befunde:
- **certifi (MPL-2.0)** ist schwaches Copyleft (Dateiebene) und nach `docs/INTEGRATIONS.md` nur nach **ausdruecklicher Freigabe des Besitzers** zulaessig. **Frage an den Besitzer.**
- **tld** bietet eine Mehrfachlizenz; waehlbar waere MPL-1.1, LGPL-2.1-or-later oder GPL-2.0-only. Zu verwenden waere ausschliesslich die MPL-1.1-Option (schwaches Copyleft) oder LGPL bei dynamischer Nutzung; der genaue Hinweis der Betreuer, welche Option gilt, wurde nicht im Wortlaut gelesen: **Frage an den Besitzer**.
- python-dateutil 4.0.0 verlangt Python >= 3.11 (passt zum Projekt).
- **Alternative ohne diese Kette:** keine eigene Extraktion aus der Standardbibliothek wurde bewertet; der vorhandene `research/extract.py` arbeitet auf Text, nicht auf HTML.

**Brave/Mojeek/Google/Bing:** keine Python-Abhaengigkeit (HTTPS-Aufruf mit `urllib.request`, wie im bestehenden Cloud-Provider). **SearXNG als getrennter Prozess:** keine Python-Abhaengigkeit fuer JARVIS; die Abhaengigkeiten des Dienstes selbst wurden nicht erhoben (offen).

## Sicherheitshinweise
- **Advisories:** trafilatura und SearXNG: keine veroeffentlichten Advisories (siehe Pflege). Andere Pakete der Kette: nicht gelesen, offen.
- **Native Binaerteile:** `lxml` (libxml2/libxslt), `charset-normalizer` (kompilierte Wheel) und `regex` liefern Maschinencode aus PyPI-Wheels. libxml2/libxslt verarbeiten **nicht vertrauenswuerdiges HTML aus dem Netz**: ein Parser-Fehler dort ist eine reale Angriffsflaeche. Entschaerfung nur durch Pinning, Aktualisierung und Grenzen (Maximalgroesse der Eingabe, Zeitlimit, Parser im Worker-Prozess): Ausgestaltung offen, Sache des Einbauschritts.
- **Install/Import:** reine Wheels ohne Installationsskripte fuer die trafilatura-Pakete; ob beim Import Code mit Netzzugriff laeuft, wurde nicht belegt. In den gelesenen Dateien `downloads.py` und `cli.py` stehen keine Treffer fuer `telemetry`, `analytics`, `sentry` (Textsuche, Rohdateien von `master`).
- **Ungeprueft/hoeherer Aufwand:** trafilatura besitzt Funktionen zum **Laden** (`fetch_url`, Feeds, Sitemaps, Crawler), die den Netzwerkzugriff **am Tool-System vorbei** ausfuehren wuerden. Sie duerfen nicht verwendet werden; jede Seite wird nur ueber das `browser`-Tool geholt, erst danach `extract()` auf den Text. Das ist eine Einbauvorgabe, kein Befund.
- **Query-Parameter:** Suchanfragen aus Zieltext koennen Secrets enthalten (Prompt-Injection / versehentliche Weitergabe). Vor dem Senden an einen Suchanbieter muss die bestehende Redaktion greifen: Einbauvorgabe.
- **SearXNG-Betrieb:** Bot-Limiter braucht Valkey ("The limiter requires a Valkey database."), die Client-IP kommt aus `X-Forwarded-For`; das JSON-Format ist nur verfuegbar, wenn `json` in `search.formats` steht (Beispielkonfiguration der Doku zeigt nur `html`). Fuer einen privaten, nur lokal erreichbaren Dienst ist ein Betrieb ohne oeffentliche Erreichbarkeit zu verlangen.
- **Rechte:** ausgehendes HTTPS zum Suchanbieter; keine Administratorrechte, keine Server-Ports (bei Brave/Mojeek).

## Datenabfluss
**Textextraktion (trafilatura):** `extract()` arbeitet auf einem uebergebenen String und braucht laut Dokumentation keinen Netzzugriff ("raw documents (strings) or parsed HTML"); die Doku erwaehnt weder Telemetrie noch robots.txt. Es wurde kein Modell-Download gefunden (Projekt ohne Modelle laut PyPI-Metadaten; **nicht** ausdruecklich vom Projekt bestaetigt). Telemetrie: keine belegt, aber auch nicht ausgeschlossen (nur Teilsuche in zwei Dateien). Beim Laden setzt trafilatura den User-Agent `trafilatura/<Version> (+https://github.com/adbar/trafilatura)` (Fundstelle: `trafilatura/settings.py`, Zeile 88); `downloads.py` enthielt **keinen** Treffer fuer robots.txt. **Die Bibliothek prueft robots.txt also nicht beim Laden.** Das gilt gleichermassen fuer den heutigen Research-Agent: im Repository gibt es keinen Treffer fuer `robots` (Textsuche in `src`, `docs`, `README.md`).

**Was geht an den Suchanbieter?** Immer: die **Suchanfrage im Klartext**, die **IP-Adresse des Rechners** und (Brave/Mojeek) ein **API-Schluessel**, der dem Konto zugeordnet ist (Aufbau des Schluessel-Headers: nicht gelesen). Damit kann der Anbieter Anfragen dem Konto zuordnen.
- **Brave:** Produktseite: "Architectural ZDR ... Your queries never leave Brave", "Queries never shared or trained on", > "every query ends on infrastructure we operate end to end, so there's no third party to retain it"; > "Full-funnel Zero Data Retention" ist ein Merkmal der **Enterprise**-Tarife. Die Seite enthaelt **keine** ausdrueckliche Aussage zu Protokollierung ("no logging") oder IP-Adressen. Die Nutzungsbedingungen geben Brave eine Lizenz an den Suchdaten (§9(b)) "for purposes of use with the API, providing the Search Results" und verweisen auf eine getrennte Datenschutzerklaerung (§7(a)), die **nicht gelesen** wurde (die Datenschutzseite des Browsers erwaehnt die API nicht). **Aufbewahrung der Anfragen im Standard-Tarif: nicht belegt.**
- **Mojeek:** > "Standard 90-day data retention with ZDR available on request." / > "owned and operated in Europe with no sub-processors" / Mojeek ist "Processor", der Kunde "controller" (Produktseite); die Nutzungsbedingungen nennen Mojeek und den Kunden dagegen als **unabhaengige Verantwortliche** (Klausel 1.9): **Widerspruch zwischen den beiden offiziellen Seiten.**
- **SearXNG (selbst betrieben):** README: > "Users are neither tracked nor profiled." (keine Aussage zu Logs). Der Dienst **leitet jede Anfrage an die konfigurierten Suchmaschinen weiter** (Funktionsprinzip einer Metasuche; die Liste der Engines und deren Bedingungen wurden nicht gelesen): die Anfrage verlaesst den Rechner also **trotzdem**, nur ueber die IP des SearXNG-Hosts und an mehrere Drittanbieter, deren Nutzungsbedingungen (automatisierte Abfragen) ungeprueft sind: **offen**.

**Nutzungsbedingungen und Rate-Limits der Zielseiten (robots.txt):** Die URLs, die der Research-Agent liest, stammen von beliebigen Webseiten. robots.txt und Nutzungsbedingungen dieser Seiten wurden **nicht** gelesen, weil sie je Seite verschieden sind; belegt ist nur, dass JARVIS und trafilatura robots.txt derzeit nicht auswerten (s. o.). Der RFC zu robots.txt und eine Mindestpause je Host wurden **nicht** geprueft. Rate-Limits der Suchanbieter siehe "Pflege"; der Agent hat heute `max_sources = 8` Seiten je Task und `max_actions = 40` (`config/jarvis.toml`).

**Speicherorte:** keine. trafilatura legt laut Doku nichts ab (nicht ausdruecklich belegt); Ergebnisse von Suchanbietern duerfen gemaess Brave-Startup-Bedingungen nur fluechtig, nach Mojeek-Startup hoechstens eine Stunde gespeichert werden. Das **steht im Konflikt** mit `persistent-results` (`[history]`) und `memory`, sobald Suchtreffer dort landen koennten (Einbauvorgabe: Treffer-URLs/Titel nicht dauerhaft speichern, es sei denn der Tarif enthaelt Speicherrechte).

## Pinning mit Hash
Hashes stammen aus der PyPI-JSON-Abfrage am 2026-11-04 (Windows 64 Bit, Python 3.11), nicht aus einer eigenen Berechnung; es wurde nichts heruntergeladen und verglichen. Nur fuer **trafilatura** (die Suchdienste haben kein Paket).

```
trafilatura==2.3.1         --hash=sha256:f86bad2ee36f82884e14dee84c83aae0f0ac0127da5c65764e82f3846716b822   (py3-none-any, 158 660 Byte)
certifi==2026.10.23        --hash=sha256:e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1   (py3-none-any, 135 082 Byte)
charset-normalizer==3.5.2  --hash=sha256:87e50a3e7cb90af586b6c5faf23e302a970415ac73bd7bd90a515a04b427ef96   (cp311-win_amd64, 214 932 Byte)
courlan==1.4.0             --hash=sha256:ad1dbdefd912ca7238d4607dc855df5df097f56bac175dd662c84eed3802f49e   (py3-none-any, 34 193 Byte)
babel==2.18.0              --hash=sha256:e2b422b277c2b9a9630c1d7903c2a00d0830c409c59ac8cae9081c92f1aeba35   (py3-none-any, 10 196 845 Byte)
tld==0.13.2                --hash=sha256:9b8fdbdb880e7ba65b216a4937f2c94c49a7226723783d5838fc958ac76f4e0c   (py2.py3-none-any, 296 743 Byte)
urllib3==2.8.0             --hash=sha256:0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3   (py3-none-any, 135 717 Byte)
htmldate==1.11.0           --hash=sha256:2a5a0d80cce38d3f986a64bb9ab64ba03e5953159b38fd78a841492131ead348   (py3-none-any, 33 365 Byte)
dateparser==1.5.0          --hash=sha256:7c4e088f25458f57db391510035af0878439a6df71d159318dcdb0a7553932e3   (py3-none-any, 373 447 Byte)
python-dateutil==4.0.0     --hash=sha256:a5e246f79eb80475e691bf93862cead98decd8a498cf53ba0516fcdc0f50dc1c   (py3-none-any, 92 853 Byte)
```

Fortsetzung (reine Python-Wheels bzw. Windows-Wheels):

```
tzdata==2026.6             --hash=sha256:0a10eec6e13ef16b627fabed9a5f2ba61a62b1c67f327305f4e7e412a70b4aec   (py2.py3-none-any, 348 210 Byte)
pytz==2026.6               --hash=sha256:7fed3fee8fd6bd4a2b7b75a8d56021d0624127bf69bd5691f115db929ac570b3   (py2.py3-none-any, 506 321 Byte)
regex==2026.9.29           --hash=sha256:1043aedf5917caa861bcb25a9c11460049656bdf0017a90a309fa8f255467725   (cp311-win_amd64, 280 641 Byte)
tzlocal==5.4.5             --hash=sha256:ecab534f6d65d9deb4c4ea52c121ab6dd5958e9b878e71dcb102578269752454   (py3-none-any, 18 215 Byte)
lxml==6.1.3                --hash=sha256:7ae4949f212a53b007dbc355884fda122545c5764a54256c9217e419a62a6559   (cp311-win_amd64, 4 032 700 Byte)
justext==3.0.2             --hash=sha256:62b1c562b15c3c6265e121cc070874243a443bfd53060e869393f09d6b6cc9a7   (py2.py3-none-any, 837 940 Byte)
lxml-html-clean==0.4.6     --hash=sha256:cc037270ba500a65e7235409dcddcae8ef37300f26dea826b61d917bf0236880   (py3-none-any, 14 952 Byte)
```

Die Linux-Hashes (manylinux-Wheels fuer lxml, charset-normalizer und regex) wurden **nicht** erhoben, ebenso keine Hashes fuer Python 3.12 oder neuer. Vor einem Einbau muessen sie im Einbauschritt mit `pip install --require-hashes` ergaenzt werden; die Hashes sind danach neu zu pruefen, weil Wheels (z. B. `dateparser` am Pruefungstag veroeffentlicht) laufend erscheinen.

## Lizenzausschluss (AGPL/GPL)
- **trafilatura und seine Kette:** kein Paket steht ausschliesslich unter AGPL/GPL. Zwei Punkte brauchen die Besitzerentscheidung: **certifi** (MPL-2.0) und **tld** (Mehrfachlizenz mit GPL-2.0-only/LGPL-Optionen neben MPL-1.1; nur die MPL-1.1-Option waere zulaessig). Frueher als 1.8.0 war trafilatura GPLv3+: diese Versionen sind ausgeschlossen.
- **SearXNG (AGPL-3.0) wird nicht als Bibliothek, nicht im JARVIS-Prozess und nicht im Repository eingebunden.** Falls der Besitzer es nutzt, dann **nur als getrennter, selbst betriebener Dienst** in einem eigenen Prozess (Container oder eigener Rechner), den JARVIS ausschliesslich ueber HTTP anspricht, ohne Code, Konfiguration oder Pakete von SearXNG aus dem Repository zu importieren oder weiterzugeben. Begruendung: Die AGPL-Pflichten (Quelltextangebot bei Nutzern ueber das Netz, Copyleft bei verbundenen Werken) beziehen sich auf das SearXNG-Werk selbst; eine Kopplung nur ueber ein oeffentlich dokumentiertes HTTP-Protokoll zwischen zwei getrennten Programmen fuehrt JARVIS nicht in dieses Werk ein. **Das ist eine technische Einschaetzung, keine Rechtsberatung; die Rechtswirkung wurde an den offiziellen Quellen (Lizenztext) nicht ueber den Titel hinaus belegt.** Aenderungen an SearXNG selbst (Fork) loesen die AGPL-Pflichten des Betreibers aus: nicht empfohlen.
- **Brave, Mojeek, Google, Bing:** keine Lizenz im Sinne dieser Regel (Dienste mit Vertrag).

## Entscheidung
nehmen
Besitzer-Freigabe: 2026-11-04

Das ist die **Empfehlung dieser Pruefung; die Entscheidung liegt beim Besitzer (offen)**. Sie gilt **nur unter den Bedingungen unten** und ersetzt keine Freigabe: ohne ausdrueckliche Besitzerfreigabe wird nichts eingebaut. Zusammengefasst:

1. **Suchquelle: genau eine, nehmen = Brave Search API** (Tarif "Search", HTTPS mit `urllib.request`, keine neue Abhaengigkeit). Gruende: offizielle, vertraglich geregelte Schnittstelle statt Scraping, schriftliche Nutzungsbedingungen und Rate-Limits, Zero-Data-Retention-Aussage des Anbieters (Reichweite fuer den Standardtarif nicht belegt), kein Paket mit Lizenz-/Lieferkettenrisiko. Herkunft der Suchdaten: die FAQ der Produktseite hat die Fragen "Does Brave ever use Google or Bing results?" und "Where does Brave's data come from?"; die Antworten wurden nicht gelesen (offen). Bedingungen: (a) Standard aus, nur auf ausdrueckliche Konfiguration, Schluessel nur aus der Umgebung; (b) Treffer **nicht dauerhaft speichern** (Bedingungen §3(b)(i)), solange kein Tarif mit Speicherrechten gewaehlt ist; (c) die vorgesehene Verwendung (Treffer als Eingabe fuer Antworten) mit Blick auf §3(b)(xiii) vom Besitzer bestaetigen lassen; (d) Anfrage vor dem Senden schwaerzen; (e) Kosten: $5 je 1 000 Anfragen, $5 bzw. "bis $20" Gratisguthaben monatlich: **neue Kosten, Besitzerentscheidung**.
2. **Extraktion: nehmen = trafilatura 2.3.1** nur auf bereits ueber das `browser`-Tool geladenem HTML; **nicht** `fetch_url`, Feeds, Sitemaps oder Crawler benutzen. Bedingungen: **Freigabe von certifi (MPL-2.0) und tld (MPL-1.1-Option)** durch den Besitzer; ein optionales Extra `research-extract` (nicht in den Basis-Abhaengigkeiten), Hash-Pinning aller Wheels fuer Windows und Linux, Windows-Nachweis aus dem CI-Lauf, Eingabegroesse und Zeit begrenzen. **Ohne diese Freigabe gilt `nicht nehmen`** und der bisherige `research/extract.py` bleibt.
3. **Alternative / Rueckfall:** **SearXNG** nur als getrennter, privater, selbst betriebener Dienst (AGPL, siehe oben), falls der Besitzer keinen kostenpflichtigen Anbieter will; Nachteile: Betrieb unter Windows nicht belegt, Anfragen gehen trotzdem an mehrere Drittmaschinen, Bedingungen dieser Engines ungeprueft. **Mojeek** als zweite Wahl (guenstiger, EU-Betreiber, aber Widersprueche in den Bedingungen: Verantwortlicher/Auftragsverarbeiter, KI-Nutzung, 90 Tage Aufbewahrung).
4. **Nicht nehmen:** Google Custom Search JSON API (fuer neue Kunden geschlossen, Ende 2027-01-01), Bing Search APIs (eingestellt 2025-08-11), Scraping von Trefferseiten.

**Offene Fragen an den Besitzer**
1. Darf eine kostenpflichtige Suchquelle (Brave, $5 je 1 000 Anfragen, Bankkarte noetig) ueberhaupt angebunden werden? Welches Monatsbudget?
2. Ist die vorgesehene Verwendung der Treffer fuer Antworten mit Brave §3(b)(xiii) (KI-Verwendung) vereinbar? Soll vorher eine schriftliche Auskunft des Anbieters eingeholt werden?
3. Freigabe von **certifi (MPL-2.0)** und **tld (MPL-1.1-Option)** als schwaches Copyleft?
4. Sollen Treffer (URLs, Titel) dauerhaft gespeichert werden duerfen? Dann ist ein Tarif mit Speicherrechten noetig (Preis und Bedingungen nicht belegt).
5. Wie soll mit **robots.txt und Seiten-Nutzungsbedingungen** umgegangen werden, da JARVIS sie bisher nicht beachtet? Vorschlag: robots.txt vor jedem Abruf lesen und Disallow beachten, mindestens eine Sekunde Pause je Host; die Auslegung des RFC wurde hier nicht geprueft.
6. Darf Suchanfragetext den Rechner verlassen (Klartext + IP an Brave)? Welche Redaktion soll gelten?
7. Soll der SearXNG-Rueckfall ueberhaupt vorbereitet werden (Betrieb im Container unter Windows)?

## Pruefung (Datum und Quelle)
2026-11-04. Quellen:
- trafilatura: https://pypi.org/pypi/trafilatura/json (2.3.1), https://raw.githubusercontent.com/adbar/trafilatura/master/LICENSE, https://raw.githubusercontent.com/adbar/trafilatura/master/README.md (Zeilen 108 bis 112), https://github.com/adbar/trafilatura, https://github.com/adbar/trafilatura/security/advisories, https://trafilatura.readthedocs.io/en/latest/usage-python.html, `trafilatura/settings.py`, `downloads.py`, `cli.py` (Rohdateien `master`).
- Transitive Pakete: PyPI-JSON `https://pypi.org/pypi/<name>/json` fuer certifi, charset-normalizer, courlan, babel, tld, urllib3, htmldate, dateparser, python-dateutil, tzdata, regex, tzlocal, pytz, lxml, justext, lxml-html-clean; https://raw.githubusercontent.com/jawah/charset_normalizer/master/LICENSE.
- SearXNG: https://github.com/searxng/searxng, https://raw.githubusercontent.com/searxng/searxng/master/LICENSE, https://github.com/searxng/searxng/security/advisories, https://docs.searxng.org/admin/installation.html, https://docs.searxng.org/admin/searx.limiter.html, https://docs.searxng.org/admin/settings/settings_search.html.
- Brave: https://brave.com/search/api/, https://api-dashboard.search.brave.com/documentation/guides/rate-limiting, https://api-dashboard.search.brave.com/terms-of-service, https://api-dashboard.search.brave.com/documentation/pricing (Inhalt im Abruf leer), https://brave.com/privacy/browser/ (erwaehnt die API nicht).
- Google: https://developers.google.com/custom-search/v1/overview. Bing: https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement (Stand der Seite 2025-05-16).
- Mojeek: https://www.mojeek.com/services/search/web-search-api/, https://www.mojeek.com/about/legal/api-terms.html. (Die ersten Abrufe von `/services/api/` lieferten 404; die Preis-Suchtreffer einer Suchmaschine wurden nur zum Auffinden der offiziellen URL genutzt.)
- Repository (Stand 4c28988): `config/jarvis.toml` `[research]`, `src/jarvis/research/`, `src/jarvis/voice/openai_provider.py`, `docs/INTEGRATIONS.md`.

**Nicht erreicht oder nicht gelesen (ehrlich):** die API-Preis-Dokumentation und die Datenschutzerklaerung von Brave (leer bzw. nicht verlinkt gelesen), die Allgemeinen Bedingungen von Mojeek, die Google-Bedingungen, Advisories der transitiven Pakete, die Security-Policy von trafilatura, die SearXNG-Release-Liste, Linux-Hashes. Die Hauptquellen jedes Kandidaten (Lizenz/Bedingungen, PyPI, Advisories-Seite des Repositories) waren erreichbar; der Schritt wird daher nicht als `blocked` gemeldet, die Luecken stehen oben.
