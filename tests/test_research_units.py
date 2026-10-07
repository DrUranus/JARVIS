"""Research layer units: URL policy, models and limits, extraction, cross-check, hand-off to other agents."""
from __future__ import annotations

import json

import pytest

from jarvis.research import (Claim, ClaimKind, Conflict, Figure, InvalidResearchRequest, ResearchLimits, ResearchResult, ResearchUrlPolicy, Source,
                             SourceStatus, build_plan)
from jarvis.research import analysis as A
from jarvis.research import extract as X
from jarvis.research.handoff import ResearchData, collect, pick_figure
from jarvis.research.urls import normalize_domains

P = ResearchUrlPolicy()


# ---- URL policy ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://example.com", "http://example.com/a/b?x=1", "https://sub.example.co.uk:8443/p", "https://8.8.8.8/", "https://[2606:4700::1111]/x",
                                 "HTTPS://Example.COM/Path"])
def test_public_urls_are_accepted(url):
    d = P.check(url)
    assert d.ok and d.url.startswith(("http://", "https://"))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd", "file://C:/Windows/win.ini", "ftp://example.com/x",
                                 "mailto:a@b.de", "chrome://settings", "view-source:https://example.com", "about:blank", "//evil.example.com/x", "/relative/path", "example.com",
                                 "vbscript:x", "blob:https://example.com/x", "ws://example.com/"])
def test_dangerous_or_non_http_schemes_are_refused(url):
    assert not P.check(url).ok


@pytest.mark.parametrize("url", ["http://localhost/", "http://LOCALHOST:8080/", "http://127.0.0.1/", "http://127.0.0.1:9/x", "http://0.0.0.0/", "http://10.0.0.5/admin",
                                 "http://172.16.0.1/", "http://172.31.255.255/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
                                 "http://[fe80::1]/", "http://[fd00::1]/", "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://intranet/", "http://printer/",
                                 "https://router.local/", "https://x.internal/", "https://nas.lan/", "https://a.home.arpa/", "http://metadata.google.internal/",
                                 "http://100.100.100.200/", "http://foo.localhost/", "http://corp.corp/"])
def test_private_internal_loopback_and_metadata_addresses_are_refused(url):
    d = P.check(url)
    assert not d.ok and d.reason


@pytest.mark.parametrize("url", ["http://2130706433/", "http://0x7f000001/", "http://0x7f.1/", "http://127.1/", "http://0177.0.0.1/", "http://1.2.3/", "http://3232235777/",
                                 "http://017700000001/"])
def test_obfuscated_numeric_hosts_are_refused(url):
    assert not P.check(url).ok


@pytest.mark.parametrize("url", ["https://user:pw@example.com/", "https://user@example.com/", "http://a:b@10.0.0.1/", "https://example.com@evil.com/", "https://:pw@example.com"])
def test_credentials_in_urls_are_refused(url):
    assert not P.check(url).ok


@pytest.mark.parametrize("url", ["", "   ", None, 5, [], "http://", "https:///path", "http://a b.com", "https://exa\x00mple.com", "http://exa\nmple.com", "x" * 3000,
                                 "https://example.com/" + "a" * 2100, "http://[::1", "https://example.com:99999/"])
def test_malformed_urls_are_refused(url):
    assert not P.check(url).ok


def test_private_hosts_need_the_users_exact_browser_allowance_and_metadata_never():
    ok = ResearchUrlPolicy(private_hosts_allowed=("127.0.0.1",))
    assert ok.check("http://127.0.0.1:8000/x").ok and not ok.check("http://127.0.0.2/").ok and not ok.check("http://localhost/").ok
    assert not ResearchUrlPolicy(private_hosts_allowed=("169.254.169.254", "metadata.google.internal")).check("http://169.254.169.254/").ok


def test_domain_allow_and_exclusion_lists():
    pol = ResearchUrlPolicy(allowed_domains=("example.com",), excluded_domains=("bad.example.com",))
    assert pol.check("https://example.com/").ok and pol.check("https://www.example.com/").ok
    assert not pol.check("https://other.org/").ok and not pol.check("https://bad.example.com/").ok and not pol.check("https://notexample.com/").ok
    assert not ResearchUrlPolicy(excluded_domains=("example.com",)).check("https://a.example.com/").ok


def test_canonicalisation_and_dedup_key():
    a = P.check("HTTP://Example.COM:80/a?utm_source=x&q=1#frag")
    assert a.url == "http://example.com/a?q=1"
    keys = {P.check(u).key for u in ("https://example.com", "https://example.com/", "https://www.example.com/", "https://example.com/?utm_campaign=z", "https://example.com:443/#x")}
    assert len(keys) == 1
    assert P.check("https://example.com/a").key != P.check("https://example.com/b").key


def test_secrets_in_query_strings_are_never_carried_on():
    d = P.check("https://example.com/p?token=abc&api_key=k&password=pw&session=s&a=b&code=1&sig=2")
    assert d.url == "https://example.com/p?a=b" and "abc" not in d.url


def test_domain_normalisation():
    assert normalize_domains(["Example.COM", ".b.org", "example.com"]) == ("example.com", "b.org")
    for bad in ("x", ["a b"], ["a..b"], [5], ["x" * 300], ["a/b"], ["a"] * 60):
        with pytest.raises(ValueError):
            normalize_domains(bad)


# ---- plan / limits -----------------------------------------------------------------------------------------------------------------------------
L = ResearchLimits(max_sources=5, max_actions=20, timeout=60)


def test_plan_defaults_and_requested_values_only_lower_limits():
    p = build_plan("Preise", {"urls": ["https://a.test/"]}, L)
    assert (p.max_sources, p.max_actions, p.timeout) == (5, 20, 60.0) and p.questions == ("Preise",) and not p.follow_links
    q = build_plan("x", {"urls": ["https://a.test/"], "max_sources": 2, "max_actions": 3, "timeout": 10}, L)
    assert (q.max_sources, q.max_actions, q.timeout) == (2, 3, 10.0)
    big = build_plan("x", {"urls": ["https://a.test/"], "max_sources": 500, "max_actions": 10 ** 6, "timeout": 10 ** 6}, L)
    assert (big.max_sources, big.max_actions, big.timeout) == (5, 20, 60.0)


@pytest.mark.parametrize("data", [{}, {"urls": []}, {"urls": "x" * 3000}, {"urls": ["a"] * 41}, {"urls": [5]}, {"urls": ["https://a.test/"], "max_sources": 0},
                                  {"urls": ["https://a.test/"], "max_sources": -1}, {"urls": ["https://a.test/"], "max_sources": True}, {"urls": ["https://a.test/"], "timeout": float("inf")},
                                  {"urls": ["https://a.test/"], "questions": ["q"] * 11}, {"urls": ["https://a.test/"], "questions": [5]}, {"urls": ["https://a.test/"], "follow_links": "yes"},
                                  {"urls": ["https://a.test/"], "allowed_domains": ["a b"]}, {"urls": ["https://a.test/"], "login": True},
                                  {"urls": ["https://a.test/"], "confirmed": True}, "not a mapping"])
def test_malformed_requests_are_refused(data):
    with pytest.raises(InvalidResearchRequest):
        build_plan("x", data, L)  # type: ignore[arg-type]


def test_plan_serialises_without_urls_or_secrets():
    p = build_plan("Preise", {"urls": ["https://a.test/?token=secret"]}, L)
    assert "secret" not in json.dumps(p.to_dict()) and "secret" not in repr(p)


# ---- models -------------------------------------------------------------------------------------------------------------------------------------
def test_source_is_bounded_and_serialisable():
    s = Source("https://a.test/" + "x" * 900, "t" * 500, "a.test", "2026-01-01T00:00:00+00:00", 7.5, SourceStatus.OK, "n" * 500, "e" * 5000)
    assert len(s.url) <= 500 and len(s.title) <= 200 and len(s.excerpt) <= 500 and s.relevance == 1.0
    json.dumps(s.to_dict())
    assert Source("u", relevance=float("nan")).relevance == 0.0 and Source("u", relevance=-3).relevance == 0.0
    assert "eeee" not in repr(s)


def test_a_fact_needs_a_source_and_figures_need_finite_numbers():
    with pytest.raises(InvalidResearchRequest):
        Claim("x", ClaimKind.FACT)
    Claim("x", ClaimKind.INFERENCE)
    Claim("x", ClaimKind.UNCERTAIN)
    for bad in (float("nan"), float("inf"), True, "5"):
        with pytest.raises(InvalidResearchRequest):
            Figure("a", bad, "EUR", "u")  # type: ignore[arg-type]


def test_result_truncation_keeps_the_result_valid_and_says_so():
    sources = tuple(Source(f"https://a.test/{i}", f"title {i}", "a.test", "t", 0.5, SourceStatus.OK, "", "x" * 400) for i in range(40))
    claims = tuple(Claim("c" * 280, ClaimKind.FACT, (f"https://a.test/{i}",)) for i in range(40))
    figs = tuple(Figure(f"label {i}", float(i), "EUR", "https://a.test/1", "x" * 150) for i in range(200))
    out = ResearchResult("obj", "s" * 5000, sources, claims, figs).to_dict(6000)
    assert len(json.dumps(out)) <= 6000 and out["truncated"] is True and out["kind"] == "research_result"
    small = ResearchResult("obj", "s", sources[:2], claims[:2]).to_dict(20_000)
    assert small["truncated"] is False and len(small["sources"]) == 2


# ---- extraction ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,value", [("1.299,00", 1299.0), ("1,299.00", 1299.0), ("49,90", 49.9), ("49.90", 49.9), ("1 299", 1299.0), ("1.299", 1299.0),
                                       ("12,5", 12.5), ("1,234", 1234.0), ("7", 7.0), ("0,99", 0.99)])
def test_number_parsing_german_and_english(raw, value):
    assert X.parse_number(raw) == value


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3.4x", "--", "€"])
def test_unparseable_numbers_are_none(raw):
    assert X.parse_number(raw) is None


def test_figures_have_labels_units_and_sentence_local_context():
    t = "Innenreinigung ab 49,90 € inklusive Staubsaugen. Komplettpaket 1.299,00 EUR. Rabatt 15 %. Kosten $20 pro Monat."
    fs = {f.label: (f.value, f.unit) for f in X.figures(t, "https://a.test/")}
    assert fs["innenreinigung"] == (49.9, "EUR") and fs["komplettpaket"] == (1299.0, "EUR") and fs["rabatt"] == (15.0, "%") and any(u == "USD" for _, u in fs.values())
    assert all(f.source_url == "https://a.test/" for f in X.figures(t, "https://a.test/"))


def test_figures_are_never_invented():
    assert X.figures("Keine Zahlen hier, nur Text über Autos.", "u") == []
    assert len(X.figures(" ".join(f"Paket{i} {i} €" for i in range(500)), "u")) <= X.MAX_FIGURES_PER_PAGE


def test_classification_fact_opinion_uncertain():
    assert X.classify("Außenwäsche ab 25 €.") is ClaimKind.FACT
    assert X.classify("Wir sind der beste Anbieter der Region!") is ClaimKind.OPINION
    assert X.classify("Marktführer mit unschlagbaren Preisen") is ClaimKind.OPINION
    assert X.classify("Preise angeblich ab 39 €.") is ClaimKind.UNCERTAIN
    assert X.classify("Es soll bald eine Aktion geben, möglicherweise.") is ClaimKind.UNCERTAIN


def test_keywords_relevance_and_passages():
    kws = X.keywords(["Preise für die Innenreinigung?", "Fahrzeugaufbereitung"])
    assert "innenreinigung" in kws and "preise" in kws and "für" not in kws and "die" not in kws
    text = "Hallo. Innenreinigung ab 50 €. Irrelevanter Satz ohne Bezug hier. Preise für die Fahrzeugaufbereitung sind fair."
    assert X.relevance(text, kws) > 0.5 and X.relevance("nichts", kws) == 0.0 and X.relevance("x", []) == 0.0
    ps = X.passages(text, kws, 2)
    assert len(ps) == 2 and all("Irrelevanter" not in p for p in ps)


# ---- cross-check ----------------------------------------------------------------------------------------------------------------------------------
def fig(label, value, url, unit="EUR"):
    return Figure(label, value, unit, url)


def test_conflicting_figures_are_marked_with_all_sides():
    cs = A.crosscheck([fig("innenreinigung", 50, "u1"), fig("innenreinigung", 80, "u2"), fig("innenreinigung", 52.5, "u3"), fig("wäsche", 25, "u1"), fig("wäsche", 26, "u2")])
    assert len(cs) == 1 and cs[0].label == "innenreinigung" and dict(cs[0].entries) == {"u1": 50, "u2": 80, "u3": 52.5}
    assert cs[0].to_dict()["status"] == "CONFLICT"


def test_agreeing_or_single_source_figures_are_no_conflict():
    assert A.crosscheck([fig("a", 100, "u1"), fig("a", 105, "u2")]) == []          # within 10 %
    assert A.crosscheck([fig("a", 100, "u1"), fig("a", 300, "u1")]) == []          # one source only: nothing to compare
    assert A.crosscheck([fig("a", 100, "u1", "EUR"), fig("a", 300, "u2", "USD")]) == []   # different units are not comparable
    assert len(A.crosscheck([fig("a", 100, "u1"), fig("a", 300, "u2")], tolerance=0.9)) == 0


def test_corroboration_needs_the_same_statement_incl_numbers():
    claims = A.build_claims({"u1": ["Außenwäsche ab 25 € im Paket."], "u2": ["Außenwäsche ab 25 € im Paket."], "u3": ["Außenwäsche ab 27 € im Paket."]}, [])
    by = {c.text: c for c in claims}
    assert by["Außenwäsche ab 25 € im Paket."].corroborated and set(by["Außenwäsche ab 25 € im Paket."].source_urls) == {"u1", "u2"}
    assert not by["Außenwäsche ab 27 € im Paket."].corroborated


def test_statements_with_conflicting_figures_become_uncertain():
    conflicts = A.crosscheck([fig("innenreinigung", 50, "u1"), fig("innenreinigung", 80, "u2")])
    claims = A.build_claims({"u1": ["Innenreinigung ab 50 €."], "u2": ["Innenreinigung ab 80 €."]}, conflicts)
    assert {c.kind for c in claims} == {ClaimKind.UNCERTAIN}


def test_inferences_are_labelled_and_skip_conflicts():
    figs = [fig("wäsche", 25, "u1"), fig("wäsche", 27, "u2"), fig("innen", 50, "u1"), fig("innen", 80, "u2")]
    inf = A.price_inferences(figs, A.crosscheck(figs))
    assert len(inf) == 1 and inf[0].kind is ClaimKind.INFERENCE and "INFERENCE" in inf[0].text and "wäsche" in inf[0].text


def test_summary_never_claims_a_result_when_nothing_was_read():
    s = A.summarize("x", [Source("u", status=SourceStatus.UNAVAILABLE)], [], [])
    assert "nothing could be read" in s and "0 of 1" in s


# ---- hand-off ------------------------------------------------------------------------------------------------------------------------------------
class PR:
    def __init__(self, out, status="SUCCEEDED"):
        self.output, self.status = out, status


RES = {"kind": "research_result", "sources": [{"url": "https://a.test/", "status": "ok", "title": "A"}, {"url": "https://b.test/", "status": "unavailable"}],
       "figures": [{"label": "umsatz", "value": 5.0, "unit": "EUR", "source_url": "https://a.test/", "context": "x"}, {"label": "bad", "value": "x", "unit": "EUR"}],
       "claims": [{"text": "t", "kind": "FACT", "sources": ["https://a.test/"]}], "conflicts": [], "uncertainties": ["u"]}


def test_collect_reads_only_successful_research_results():
    d = collect({"t1": PR(RES), "t2": PR({"kind": "other"}), "t3": PR(RES, "FAILED"), "t4": PR("garbage")})
    assert [s["url"] for s in d.sources] == ["https://a.test/", "https://b.test/"] and len(d.figures) == 1 and d.has_data and len(d.ok_sources) == 1
    assert not collect({"t3": PR(RES, "FAILED")}).has_data and not collect(None).has_data and not collect({}).has_data
    assert collect({}, RES).has_data                                                    # an explicit research block works the same way


def test_collect_is_bounded_and_ignores_non_mappings():
    big = {"kind": "research_result", "sources": [{"url": f"https://a.test/{i}", "status": "ok"} for i in range(500)],
           "figures": [{"label": "a", "value": 1.0, "unit": "EUR", "source_url": "u"}] * 5000}
    d = collect({"t": PR(big)})
    assert len(d.sources) <= 40 and len(d.figures) <= 400
    assert not collect({}, "not a mapping").has_data


def test_pick_figure():
    d = collect({"t": PR(RES)})
    assert pick_figure(d, "UMSATZ")["value"] == 5.0 and pick_figure(d, "nope") is None and pick_figure(d, "umsatz", "USD") is None and pick_figure(d, "") is None


@pytest.mark.parametrize("url", ["https://example.com\\@evil.test/", "https://evil.test\\.example.com/", "http://127.0.0.1\\x", "https://example.com\\path", "C:\\Windows\\win.ini",
                                 "\\\\server\\share\\x", "file:\\\\C:\\x.txt", "https:\\\\example.com", "https://example.com/a\\..\\b"])
def test_windows_style_urls_with_backslashes_are_refused_as_ambiguous(url):
    d = P.check(url)
    assert not d.ok and d.reason
