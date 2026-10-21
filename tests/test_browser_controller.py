"""Browser tool + PermissionEngine + BrowserController, with the fake provider."""
import re
from dataclasses import replace

import pytest

from browser_util import G, HOME, NO, ONCE, R, SESSION, Y, make_rig, make_web
from jarvis.browser import BrowserErrorCode as EC
from jarvis.browser.providers.fake import FakeDoc, el
from jarvis.permissions import DecisionStatus


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path, [ONCE] * 60)


def code(out):
    """Machine-readable code of a failure: structured output (run time) or the [code] prefix of a plan-time refusal."""
    assert not out.success
    if isinstance(out.output, dict):
        return out.output["code"]
    m = re.search(r"\[([a-z_]+)\]", out.error or "")
    return m.group(1) if m else None


def level(out):
    return out.permission.level


def after_confirmation(rig, fn):
    orig = rig.prompts.confirm

    def hook(request):
        choice = orig(request)
        fn()
        return choice

    rig.prompts.confirm = hook


def doc(rig, url=HOME):
    return rig.provider.web.docs[url]


# ---- levels --------------------------------------------------------------------------------------------------------------------
def test_status_and_observation_are_green_and_need_no_confirmation(tmp_path):
    r = make_rig(tmp_path, [])  # no answers: any prompt would deny
    assert r.ok(action="status") == {"running": False, "provider": "fake"}
    assert r.prompts.requests == []


def test_start_and_stop_are_yellow_and_asked(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    out = r.run(action="start")
    assert out.success and level(out) is Y and len(r.prompts.requests) == 1
    assert r.ok(action="status")["running"] is True
    out = r.run(action="stop")
    assert out.success and level(out) is Y and r.ok(action="status")["running"] is False


def test_declined_start_launches_nothing(tmp_path):
    r = make_rig(tmp_path, [NO])
    out = r.run(action="start")
    assert not out.success and r.provider.calls_named("provider.start") == []


def test_reading_is_green_after_navigation(rig):
    rig.open()
    before = len(rig.prompts.requests)
    for action in ("pages", "active", "info", "text", "links", "forms", "find"):
        out = rig.run(action=action)
        assert out.success and level(out) is G, action
    assert len(rig.prompts.requests) == before


def test_goto_untrusted_host_is_yellow_and_trusted_host_is_green(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, trusted_hosts=("example.com",))
    r.start()
    n = len(r.prompts.requests)
    out = r.run(action="goto", url=HOME)
    assert out.success and level(out) is G and len(r.prompts.requests) == n  # trusted: no question
    out = r.run(action="goto", url="https://other.org/")
    assert out.success and level(out) is Y and len(r.prompts.requests) == n + 1


def test_wildcard_trusted_hosts_cover_subdomains_only(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, trusted_hosts=("*.example.com",))
    r.start()
    assert level(r.run(action="goto", url="https://login.example.com/")) is G
    assert level(r.run(action="goto", url=HOME)) is Y  # the apex is not a subdomain


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,<h1>x</h1>", "chrome://settings",
                                 "view-source:https://example.com/", "ftp://example.com/", "http://127.0.0.1/", "http://localhost:8080/",
                                 "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/", "https://intranet/",
                                 "http://[::1]/", "https://user:pw@example.com/", "mailto:a@b.c", ""])
def test_forbidden_addresses_are_red_and_never_reach_the_browser(rig, url):
    rig.start()
    out = rig.run(action="goto", url=url)
    assert not out.success and out.permission.status is DecisionStatus.DENIED and level(out) is R
    assert rig.provider.calls_named("page.goto") == [] and len(rig.prompts.requests) == 1  # only the start prompt


def test_private_host_can_be_allowed_by_exact_name_only(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, private_hosts_allowed=("10.0.0.5",))
    r.start()
    assert r.run(action="goto", url="http://10.0.0.5/secret").success
    assert level(r.run(action="goto", url="http://10.0.0.6/")) is R
    assert level(r.run(action="goto", url="http://169.254.169.254/")) is R  # metadata: never, even if listed elsewhere


def test_blocked_hosts_are_red(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, blocked_hosts=("other.org", "*.evil.com"))
    r.start()
    assert level(r.run(action="goto", url="https://other.org/")) is R
    assert level(r.run(action="goto", url="https://a.evil.com/")) is R


def test_redirect_to_a_forbidden_address_is_stopped(rig):
    rig.open()
    out = rig.run(action="goto", url="https://example.com/redirect-to-intranet")
    assert not out.success and code(out) == "blocked_target"  # the engine-level guard refused the redirect hop
    assert "10.0.0.5" not in rig.ok(action="active")["url"]


def test_if_a_forbidden_address_is_reached_anyway_the_page_is_left_at_once(rig):
    rig.open()
    rig.provider.sessions[0].guard = lambda url, nav: True  # simulate a hole in the provider-side guard
    out = rig.run(action="goto", url="https://example.com/redirect-to-intranet")
    assert not out.success and code(out) == "blocked_target"
    assert rig.ok(action="active")["url"] == "about:blank"  # the controller re-checks the final URL itself


def test_host_rules_of_the_engine_apply_to_navigation(tmp_path):
    from jarvis.permissions import Rule, Effect, ResourceType
    r = make_rig(tmp_path, [ONCE] * 3)
    r.engine.update_policy(r.engine.policy.__class__(tuple(r.engine.policy.rules) + (
        Rule(id="no-other", effect=Effect.DENY, tool="browser", resource_type=ResourceType.DOMAIN, resources=("other.org",)),)))
    r.start()
    out = r.run(action="goto", url="https://other.org/")
    assert not out.success and out.permission.matched_rule == "no-other"


# ---- sessions and pages -------------------------------------------------------------------------------------------------------------
def test_actions_need_a_running_browser(rig):
    for kw in ({"action": "goto", "url": HOME}, {"action": "text"}, {"action": "pages"}, {"action": "stop"}, {"action": "find"}):
        assert code(rig.run(**kw)) == "not_started", kw


def test_start_twice_is_refused(rig):
    rig.start()
    assert code(rig.run(action="start")) == "already_started"


def test_browser_not_installed_is_a_clear_structured_error(rig):
    rig.provider.unavailable = "the browser is not installed (python -m playwright install chromium)"
    out = rig.run(action="start")
    assert code(out) == "unavailable" and "playwright install" in out.error
    assert rig.ok(action="status")["running"] is False


def test_a_crashed_browser_is_reported_and_can_be_restarted(rig):
    rig.start()
    rig.provider.sessions[0].alive = False
    assert code(rig.run(action="pages")) == "not_started"
    rig.start()
    assert rig.ok(action="status")["running"] is True


def test_new_pages_listing_activate_and_close(rig):
    p1 = rig.open()
    out = rig.ok(action="new", url="https://other.org/")
    p2 = out["page"]
    assert p2 != p1 and out["title"] == "Other"
    pages = rig.ok(action="pages")
    assert {p["page"] for p in pages} == {p1, p2} and [p["page"] for p in pages if p["active"]] == [p2]
    assert rig.ok(action="activate", page=p1)["active"] is True and rig.ok(action="active")["page"] == p1
    assert rig.ok(action="close", page=p2)["closed"] == p2
    assert [p["page"] for p in rig.ok(action="pages")] == [p1]
    assert code(rig.run(action="info", page=p2)) == "page_not_found"


def test_page_limit_and_popups(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20, max_pages=2)
    r.open()
    r.ok(action="new")
    assert code(r.run(action="new")) == "rate_limited"
    # a popup opened by the page beyond the limit is closed again
    doc(r).popups["3"] = "https://other.org/"
    r.provider.sessions[0].pages()[0]  # noqa: B018
    r.ok(action="pages")
    assert len(r.ok(action="pages")) == 2


def test_popup_opened_by_a_click_becomes_a_known_page(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 10)
    r.open()
    doc(r).popups["3"] = "https://other.org/"
    btn = r.find(query="Go")["Go"]
    out = r.ok(action="click", element=btn)
    assert out["pages"] == 2
    assert {p["url"] for p in r.ok(action="pages")} == {HOME, "https://other.org/"}


def test_navigation_back_forward_reload(rig):
    rig.open()
    rig.ok(action="goto", url="https://example.com/more")
    assert rig.ok(action="back")["url"] == HOME
    assert rig.ok(action="forward")["url"] == "https://example.com/more"
    assert rig.ok(action="reload")["url"] == "https://example.com/more"


def test_reload_is_green_only_on_a_trusted_host(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, trusted_hosts=("example.com",))
    r.open()
    assert level(r.run(action="reload")) is G and level(r.run(action="back")) is Y


def test_navigation_timeout_is_structured(rig):
    rig.start()
    out = rig.run(action="goto", url="https://slow.example.com/")
    assert code(out) == "timeout" and "https://slow.example.com" not in out.error
    assert rig.ok(action="status")["running"] is True  # the browser itself is fine


def test_unexpected_provider_errors_are_reported_by_type_only(rig):
    rig.open()
    rig.provider.fail_next("page.snapshot", RuntimeError("secret page content token=abc123 password=hunter22"))
    out = rig.run(action="text")
    assert code(out) == "backend_error" and "hunter22" not in out.error and "RuntimeError" in out.error


# ---- reading ------------------------------------------------------------------------------------------------------------------
def test_text_info_links_and_forms(rig):
    rig.open()
    t = rig.ok(action="text")
    assert "Opening hours: Mon-Fri 9-17" in t["text"] and t["untrusted_content"]
    i = rig.ok(action="info")
    assert i["title"] == "Example Domain" and i["url"] == HOME and i["login_form_detected"] is False
    links = rig.ok(action="links")["links"]
    assert {l["name"] for l in links} >= {"More information", "Report PDF"}
    forms = rig.ok(action="forms")["forms"]
    assert any(f["action"] == "https://example.com/results" for f in forms)
    fields = [f for form in forms for f in form["fields"]]
    assert {"Search", "Color", "Subscribe"} <= {f["name"] for f in fields}
    assert next(f for f in fields if f["name"] == "Color")["options"] == ["red", "green", "blue"]


def test_text_is_truncated_to_the_configured_size(tmp_path):
    web = make_web()
    web.add(FakeDoc("https://big.example.com/", "Big", "x" * 5000))
    r = make_rig(tmp_path, [ONCE] * 5, web=web, max_text_chars=1000)
    r.open("https://big.example.com/")
    t = r.ok(action="text")
    assert len(t["text"]) <= 1000 and t["truncated"] is True


def test_find_filters_by_name_and_role_and_limits(rig):
    rig.open()
    out = rig.ok(action="find", query="search")
    assert {m["name"] for m in out["matches"]} == {"Search"} and len(out["matches"]) == 2
    assert [m["role"] for m in rig.ok(action="find", role="link")["matches"]][0] == "link"
    assert len(rig.ok(action="find", limit=2)["matches"]) == 2
    assert code(rig.run(action="find", limit=0)) == "invalid_input"
    assert code(rig.run(action="find", limit="abc")) == "invalid_input"


def test_field_values_are_never_exposed_only_whether_they_hold_something(rig):
    rig.open()
    box = rig.find(query="Search")["Search"]
    rig.ok(action="fill", element=box, text="my private query")
    forms = rig.ok(action="forms")
    blob = str(forms)
    assert "my private query" not in blob
    assert next(f for form in forms["forms"] for f in form["fields"] if f["name"] == "Search" and f["role"] == "searchbox")["has_value"] is True


def test_page_urls_in_results_carry_no_query_values_or_credentials(tmp_path):
    web = make_web()
    web.add(FakeDoc("https://example.com/path?token=SECRETVALUE12345&q=1#frag", "T", "x"))
    r = make_rig(tmp_path, [ONCE] * 4, web=web)
    r.start()
    out = r.ok(action="goto", url="https://example.com/path?token=SECRETVALUE12345&q=1#frag")
    assert "SECRETVALUE12345" not in str(out) and "frag" not in out["url"] and out["url"].startswith("https://example.com/path?token=…")
    assert "SECRETVALUE12345" not in r.audit_blob() and "SECRETVALUE12345" not in r.prompt_blob()


# ---- interaction --------------------------------------------------------------------------------------------------------------
def test_click_fill_select_check_submit_flow(rig):
    rig.open()
    ids = rig.find(query="")
    fill = rig.run(action="fill", element=ids["Search"] if "Search" in ids else "", text="hello")
    assert fill.success and level(fill) is Y
    assert rig.provider.typed == ["hello"]
    assert rig.ok(action="select", element=ids["Color"], value="green")["action"] == "select"
    assert rig.ok(action="check", element=ids["Subscribe"], checked=True)["action"] == "check"
    out = rig.ok(action="submit", element=ids["Search"])
    assert out["navigated"] is True and out["url"] == "https://example.com/results" and out["title"] == "Results"


def test_click_on_a_link_navigates_and_invalidates_old_references(rig):
    rig.open()
    link = rig.find(query="More information")["More information"]
    other = rig.find(query="Go")["Go"]
    out = rig.ok(action="click", element=link)
    assert out["navigated"] is True and out["url"] == "https://example.com/more"
    assert code(rig.run(action="click", element=other)) == "element_not_found"  # references of the old document are gone


def test_click_asks_and_a_session_permission_covers_only_that_element(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE, SESSION, ONCE])  # start, goto, click(session), click(other element)
    r.open()
    ids = r.find()
    first = r.run(action="click", element=ids["Go"])
    assert first.success and first.permission.scope.value == "session"
    n = len(r.prompts.requests)
    assert r.run(action="click", element=ids["Go"]).success and len(r.prompts.requests) == n  # same element: no new question
    assert r.run(action="click", element=ids["More information"]).success  # another element: asked again
    assert len(r.prompts.requests) == n + 1


def test_fill_is_always_asked_even_when_a_session_permission_is_offered(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE, SESSION, SESSION])
    r.open()
    box = r.find(query="Search")["Search"]
    for text in ("a", "b"):
        assert r.run(action="fill", element=box, text=text).success
    fills = [q for q in r.prompts.requests if q.action == "fill"]
    assert len(fills) == 2 and not any(q.session_allowed for q in fills)


def test_fill_prompt_names_the_target_and_previews_the_text_audit_does_not(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    r.open()
    box = r.find(query="Comment")["Comment"]
    r.run(action="fill", element=box, text="hello-preview-text")
    fill_prompt = [q for q in r.prompts.requests if q.action == "fill"][0]
    assert "hello-preview-text" in fill_prompt.to_text() and "Comment" in fill_prompt.to_text() and "example.com" in fill_prompt.to_text()
    assert "hello-preview-text" not in r.audit_blob()


def test_invalid_element_operations(rig):
    rig.open()
    ids = rig.find()
    assert code(rig.run(action="fill", element=ids["Go"], text="x")) == "invalid_input"        # a button is no text field
    assert code(rig.run(action="select", element=ids["Search"], value="x")) == "invalid_input"
    assert code(rig.run(action="select", element=ids["Color"], value="purple")) == "invalid_input"
    assert code(rig.run(action="check", element=ids["Go"], checked=True)) == "invalid_input"
    assert code(rig.run(action="check", element=ids["Subscribe"], checked="maybe")) == "invalid_input"
    assert code(rig.run(action="fill", element=ids["Search"], text="x" * 5000)) == "invalid_input"
    assert code(rig.run(action="fill", element=ids["Search"], text=5)) == "invalid_input"
    assert code(rig.run(action="submit", element=ids["Go"])) == "invalid_input"           # not part of a form
    assert code(rig.run(action="upload", element=ids["Search"], path=str(rig.ws / "a.txt"))) == "invalid_input"


# ---- RED: credentials, logins, dangerous targets -------------------------------------------------------------------------------------
def test_login_page_elements_are_red_and_say_why(rig):
    rig.open("https://login.example.com/")
    info = rig.ok(action="info")
    assert info["login_form_detected"] is True and "log in yourself" in info["note"]
    ids = rig.find()
    for action, kw in (("fill", {"text": "me"}), ("click", {}), ("submit", {})):
        out = rig.run(action=action, element=ids["Username" if action == "fill" else "Sign in"], **kw)
        assert not out.success and level(out) is R and out.permission.status is DecisionStatus.DENIED, action
        assert "log in" in out.permission.reason.lower() or "login" in out.permission.reason.lower()
    assert rig.provider.typed == [] and rig.provider.calls_named("page.click") == []


def test_password_and_payment_fields_are_never_filled(rig):
    rig.open()
    card = rig.find(query="Card number")["Card number"]
    out = rig.run(action="fill", element=card, text="4111")
    assert level(out) is R and rig.provider.typed == []


def test_secret_looking_text_is_never_typed_into_a_page(rig):
    rig.open()
    box = rig.find(query="Comment")["Comment"]
    for text in ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", "my password=hunter22abc", "AKIAABCDEFGHIJKLMNOP"):
        out = rig.run(action="fill", element=box, text=text)
        assert level(out) is R and not out.success, text
    assert rig.provider.typed == []
    assert "sk-ant" not in rig.prompt_blob() and "sk-ant" not in rig.audit_blob()


def test_links_to_forbidden_targets_are_red(rig):
    rig.open()
    ids = rig.find(role="link")
    for name in ("Evil", "Intranet"):
        out = rig.run(action="click", element=ids[name])
        assert level(out) is R and not out.success, name
    assert rig.provider.calls_named("page.click") == []


def test_clicking_a_file_chooser_is_red(rig):
    rig.open()
    chooser = rig.find(query="Attachment")["Attachment"]
    assert level(rig.run(action="click", element=chooser)) is R


# ---- element identity ----------------------------------------------------------------------------------------------------------------
def test_unknown_and_malformed_element_references(rig):
    rig.open()
    for ref in ("e999", "", None, 5, "../../x", "e1; rm"):
        assert code(rig.run(action="click", element=ref)) == "element_not_found", ref


def test_stale_element_changed_after_it_was_read(rig):
    rig.open()
    ids = rig.find()
    d = doc(rig)
    d.elements[3] = replace(d.elements[3], name="Delete account")  # same slot, different logical element
    out = rig.run(action="click", element=ids["Go"])
    assert code(out) == "stale_element" and rig.provider.calls_named("page.click") == []


def test_element_that_disappeared(rig):
    rig.open()
    ids = rig.find()
    d = doc(rig)
    d.elements = [e for e in d.elements if e.locator != "3"]
    assert code(rig.run(action="click", element=ids["Go"])) == "element_not_found"


def test_a_different_element_moving_into_the_slot_is_not_a_match(rig):
    rig.open()
    ids = rig.find()
    d = doc(rig)
    d.elements[3], d.elements[5] = replace(d.elements[5], locator="3"), replace(d.elements[3], locator="5")
    assert code(rig.run(action="click", element=ids["Go"])) == "stale_element"  # never "the similar one"


def test_url_change_after_reading_invalidates_the_references(rig):
    rig.open()
    ids = rig.find()
    page = rig.provider.sessions[0].pages()[0]
    page.url = "https://example.com/elsewhere"  # the page navigated on its own (script, redirect, user)
    assert code(rig.run(action="click", element=ids["Go"])) == "target_changed"


def test_query_and_fragment_changes_do_not_count_as_a_different_page(rig):
    rig.open()
    ids = rig.find()
    rig.provider.sessions[0].pages()[0].url = HOME + "?x=1#top"
    assert rig.run(action="click", element=ids["Go"]).success


def test_session_change_invalidates_everything(rig):
    rig.open()
    old = rig.find()
    old_session = rig.controller.overview()["session"]
    rig.ok(action="stop")
    rig.open()
    assert code(rig.run(action="click", element=old["Go"])) == "session_mismatch"
    assert code(rig.run(action="info", session=old_session)) == "session_mismatch"
    assert rig.run(action="info", session=rig.controller.overview()["session"]).success


def test_page_confusion_is_rejected(rig):
    p1 = rig.open()
    ids = rig.find()
    p2 = rig.ok(action="new", url="https://other.org/")["page"]
    assert code(rig.run(action="click", element=ids["Go"], page=p2)) == "target_changed"
    assert rig.run(action="click", element=ids["Go"], page=p1).success


def test_closed_page(rig):
    p1 = rig.open()
    ids = rig.find()
    rig.ok(action="new")
    rig.ok(action="close", page=p1)
    assert code(rig.run(action="click", element=ids["Go"])) == "element_not_found"  # its references were dropped with it
    assert code(rig.run(action="info", page=p1)) == "page_not_found"


def test_page_closed_by_the_site_itself(rig):
    rig.open()
    ids = rig.find()
    rig.provider.sessions[0].pages()[0].closed = True
    assert code(rig.run(action="click", element=ids["Go"])) in ("page_not_found", "not_started")


def test_element_swapped_between_confirmation_and_execution_is_not_clicked(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    r.open()
    ids = r.find()
    d = doc(r)
    after_confirmation(r, lambda: d.elements.__setitem__(3, replace(d.elements[3], name="Transfer money")))
    out = r.run(action="click", element=ids["Go"])
    assert not out.success and code(out) == "stale_element" and r.provider.calls_named("page.click") == []


def test_page_navigated_between_confirmation_and_execution_is_not_acted_on(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    r.open()
    ids = r.find()
    after_confirmation(r, lambda: setattr(r.provider.sessions[0].pages()[0], "url", "https://example.com/other"))
    out = r.run(action="fill", element=ids["Search"], text="x")
    assert not out.success and code(out) in ("target_changed", "not_authorized") and r.provider.typed == []


def test_session_swapped_between_confirmation_and_execution(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    r.open()
    ids = r.find()

    def swap():
        r.controller._session = None  # the browser was restarted by someone else meanwhile

    after_confirmation(r, swap)
    out = r.run(action="click", element=ids["Go"])
    assert not out.success and code(out) in ("not_started", "session_mismatch", "target_changed") and r.provider.calls_named("page.click") == []


def test_reads_register_references_that_expire_oldest_first(rig):
    rig.open()
    first = rig.find(query="Go")["Go"]
    for _ in range(40):
        rig.ok(action="find")
    assert code(rig.run(action="click", element=first)) == "element_not_found"  # bounded registry, never unbounded memory


# ---- budgets, kill switch --------------------------------------------------------------------------------------------------------------
def test_emergency_halt_blocks_everything_until_resumed(rig):
    rig.open()
    rig.controller.halt("test")
    for kw in ({"action": "text"}, {"action": "goto", "url": HOME}, {"action": "stop"}):
        assert code(rig.run(**kw)) == "failsafe", kw
    rig.controller.resume()
    assert rig.run(action="text").success


def test_session_action_budget_stops_runaway_loops(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20, max_actions_per_session=3)
    r.open()  # start (not counted) + goto (1)
    ids = r.find()
    assert r.run(action="click", element=ids["Go"]).success and r.run(action="click", element=ids["Go"]).success
    out = r.run(action="click", element=ids["Go"])
    assert code(out) == "failsafe" and "budget" in out.error
    assert r.run(action="text").success  # reading stays possible


def test_rate_limit(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20, max_actions_per_minute=2, max_actions_per_session=0)
    r.start()
    r.run(action="goto", url=HOME)
    out = r.run(action="goto", url=HOME)
    assert code(out) == "rate_limited" or out.success is True
    assert code(r.run(action="goto", url=HOME)) == "rate_limited"


# ---- downloads and uploads -----------------------------------------------------------------------------------------------------------------
def test_download_goes_to_an_approved_path_inside_the_workspace(rig):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    dest = rig.ws / "report.pdf"
    out = rig.ok(action="download", element=link, path=str(dest))
    assert dest.read_bytes() == b"%PDF-1.4 fake" and out["bytes"] == 13
    last = [q for q in rig.prompts.requests if q.action == "download"][-1]
    assert str(dest) in last.to_text() and not last.session_allowed  # always asked, never a session permission


def test_download_never_overwrites(rig):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    dest = rig.ws / "r.pdf"
    dest.write_bytes(b"mine")
    out = rig.run(action="download", element=link, path=str(dest))
    assert code(out) == "invalid_input" and dest.read_bytes() == b"mine"


@pytest.mark.parametrize("where", ["../outside.pdf", "sub/../../outside.pdf"])
def test_download_outside_the_workspace_is_denied_before_any_download(rig, tmp_path, where):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    out = rig.run(action="download", element=link, path=str(rig.ws / where))
    assert not out.success and out.permission.status is DecisionStatus.DENIED
    assert not (tmp_path / "outside.pdf").exists() and rig.provider.calls_named("page.download") == []


def test_download_into_a_missing_directory_or_without_extension_fails_cleanly(rig):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    assert code(rig.run(action="download", element=link, path=str(rig.ws / "nope" / "a.pdf"))) == "invalid_input"
    assert code(rig.run(action="download", element=link, path=str(rig.ws / "noext"))) == "invalid_input"


@pytest.mark.parametrize("name", ["tool.exe", "x.bat", "y.ps1", "z.msi", "a.js", "b.vbs", "c.lnk", "d.sh", "E.EXE", "f.exe."])
def test_executable_download_targets_are_red(rig, name):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    out = rig.run(action="download", element=link, path=str(rig.ws / name))
    assert level(out) is R and not out.success and not (rig.ws / name).exists()


def test_executable_offered_by_the_server_is_discarded(rig):
    rig.open()
    link = rig.find(query="Setup")["Setup"]
    out = rig.run(action="download", element=link, path=str(rig.ws / "setup.bin"))
    assert code(out) == "blocked_target" and not (rig.ws / "setup.bin").exists()


def test_downloads_nobody_asked_for_are_cancelled_and_reported(rig):
    rig.open()
    link = rig.find(query="Report PDF")["Report PDF"]
    out = rig.ok(action="click", element=link)
    assert out["blocked_downloads"] == 1 and "cancelled" in out["note"]
    assert not list(rig.ws.iterdir())


def test_download_size_limit(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, max_download_bytes=5)
    r.open()
    link = r.find(query="Report PDF")["Report PDF"]
    out = r.run(action="download", element=link, path=str(r.ws / "big.pdf"))
    assert code(out) == "download_failed" and not (r.ws / "big.pdf").exists()


def test_upload_only_from_allowed_paths_and_only_into_file_inputs(rig):
    rig.open()
    chooser = rig.find(query="Attachment")["Attachment"]
    ok = rig.ws / "note.txt"
    ok.write_text("hello")
    assert rig.ok(action="upload", element=chooser, path=str(ok))["file"] == "note.txt"
    assert rig.provider.uploaded == [str(ok.resolve())]
    out = rig.run(action="upload", element=chooser, path=str(rig.ws / ".." / "elsewhere.txt"))
    assert not out.success and out.permission.status is DecisionStatus.DENIED


@pytest.mark.parametrize("name", [".env", "id_rsa", "server.pem", "x.kdbx", "credentials", "secrets", "Cookies", "wallet.dat"])
def test_credential_files_are_never_uploaded(rig, name):
    rig.open()
    chooser = rig.find(query="Attachment")["Attachment"]
    f = rig.ws / name
    f.write_text("top secret")
    out = rig.run(action="upload", element=chooser, path=str(f))
    assert level(out) is R and not out.success and rig.provider.uploaded == []


def test_upload_of_a_missing_file_or_directory(rig):
    rig.open()
    chooser = rig.find(query="Attachment")["Attachment"]
    assert code(rig.run(action="upload", element=chooser, path=str(rig.ws / "missing.txt"))) in ("invalid_input", None)
    (rig.ws / "dir").mkdir()
    assert code(rig.run(action="upload", element=chooser, path=str(rig.ws / "dir"))) == "invalid_input"
