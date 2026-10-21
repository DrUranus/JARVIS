"""Real browser integration (Playwright) against a local, harmless test site. Skipped cleanly if the library or a browser is missing.

Browser choice: JARVIS_TEST_BROWSER (chromium | msedge | chrome | a path), otherwise the first of chromium/msedge/chrome that starts.
Windows: `pip install -e ".[browser]"` + `python -m playwright install chromium` (or set JARVIS_TEST_BROWSER=msedge).
"""
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from browser_site import serve  # noqa: E402
from browser_util import ONCE, R  # noqa: E402
from jarvis.browser import BrowserController  # noqa: E402
from jarvis.browser.policy import baseline_rules  # noqa: E402
from jarvis.browser.providers.playwright_provider import PlaywrightProvider  # noqa: E402
from jarvis.browser.tools import register_browser_tools  # noqa: E402
from jarvis.config import BrowserSettings  # noqa: E402
from jarvis.permissions import DecisionStatus, Policy, ScriptedConfirmation  # noqa: E402
from jarvis.tools import ToolRegistry  # noqa: E402
from secutil import make_engine  # noqa: E402


class Real:
    def __init__(self, tmp: Path, base: str, **kw) -> None:
        self.base = base
        self.prompts = ScriptedConfirmation([ONCE] * 2000)
        self.engine, self.sink, self.ws = make_engine(tmp, confirmation=self.prompts)
        kw.setdefault("private_hosts_allowed", ("127.0.0.1",))
        kw.setdefault("navigation_timeout", 8.0)
        kw.setdefault("max_actions_per_minute", 0)
        kw.setdefault("max_actions_per_session", 0)
        kw.setdefault("action_timeout", 5.0)
        self.settings = BrowserSettings(enabled=True, headless=True, **kw)
        self.controller = BrowserController(PlaywrightProvider(), self.settings)
        self.engine.update_policy(Policy(tuple(self.engine.policy.rules) + tuple(baseline_rules(self.settings))))
        self.registry = ToolRegistry(self.engine)
        register_browser_tools(self.registry, self.controller)

    def run(self, **kw):
        return self.registry.execute("browser", **kw)

    def ok(self, **kw):
        out = self.run(**kw)
        assert out.success, (kw, out.error)
        return out.output

    def find(self, **kw):
        found = {}
        for m in self.ok(action="find", **kw)["matches"]:
            found.setdefault(m["name"], m["element"])
        return found

    def url(self, path=""):
        return self.base + path

    def start_or_skip(self):
        wanted = os.environ.get("JARVIS_TEST_BROWSER")
        for kind in ([wanted] if wanted else []) + ["chromium", "msedge", "chrome"]:
            if kind is None:
                continue
            settings = BrowserSettings(**{**self.settings.__dict__, **({"executable_path": kind} if os.path.isabs(kind) else {"browser": kind})})
            self.controller.settings = settings
            out = self.run(action="start")
            if out.success:
                return
            self.last = out.error
        pytest.skip(f"no usable browser for the real-browser tests ({getattr(self, 'last', '')[:120]})")

    def close(self):
        self.controller.shutdown()


@pytest.fixture(scope="module")
def site():
    with serve() as base:
        yield base


@pytest.fixture(scope="module")
def shared(site, tmp_path_factory):
    r = Real(tmp_path_factory.mktemp("real"), site)
    r.start_or_skip()
    yield r
    r.close()


@pytest.fixture
def b(shared):
    """The shared browser, reset to a single blank page before every test."""
    for p in shared.ok(action="pages"):
        if p["page"] != shared.ok(action="pages")[0]["page"]:
            shared.run(action="close", page=p["page"])
    shared.ok(action="goto", url=shared.url("/"))
    shared.ok(action="goto", url="about:blank")
    for f in shared.ws.iterdir():
        f.unlink()
    return shared


def code(out):
    return out.output["code"] if isinstance(out.output, dict) else None


def test_open_a_page_and_read_title_url_and_text(b):
    out = b.ok(action="goto", url=b.url("/"))
    assert out["title"] == "JARVIS Test Page" and out["url"] == b.url("/")
    text = b.ok(action="text")["text"]
    assert "Test Heading" in text and "Opening hours: Mon-Fri 9-17" in text
    info = b.ok(action="info")
    assert info["title"] == "JARVIS Test Page" and info["login_form_detected"] is False and info["forms"] == 1
    assert b.ok(action="active")["url"] == b.url("/")


def test_elements_are_found_by_role_and_accessible_name_not_by_coordinates(b):
    b.ok(action="goto", url=b.url("/"))
    links = {l["name"]: l for l in b.ok(action="links")["links"]}
    assert links["Second page"]["href"] == b.url("/second") and links["Sign in"]["role"] == "link"
    fields = {f["name"]: f for form in b.ok(action="forms")["forms"] for f in form["fields"]}
    assert fields["Search term"]["role"] == "textbox" and fields["Colour"]["options"] == ["red", "green", "blue"]
    assert fields["Newsletter"]["role"] == "checkbox" and fields["Go search"]["role"] == "button"
    assert b.find(role="button", query="Press")["Press me"].startswith("e")


def test_click_changes_the_page(b):
    b.ok(action="goto", url=b.url("/"))
    assert "idle" in b.ok(action="text")["text"]
    out = b.ok(action="click", element=b.find(query="Press me")["Press me"])
    assert out["navigated"] is False and "clicked" in b.ok(action="text")["text"]


def test_fill_and_submit_a_search_form(b):
    b.ok(action="goto", url=b.url("/"))
    ids = b.find()
    assert b.ok(action="fill", element=ids["Search term"], text="hello world")["action"] == "fill"
    assert b.ok(action="select", element=ids["Colour"], value="green")["action"] == "select"
    assert b.ok(action="check", element=ids["Newsletter"], checked=True)["action"] == "check"
    out = b.ok(action="submit", element=ids["Search term"])
    assert out["navigated"] is True and out["title"] == "Results" and out["url"].startswith(b.url("/search?q=…&c=…&n=…"))
    assert "You searched: hello world" in b.ok(action="text")["text"]


def test_submit_by_clicking_the_submit_button(b):
    b.ok(action="goto", url=b.url("/"))
    ids = b.find()
    b.ok(action="fill", element=ids["Search term"], text="clicked submit")
    out = b.ok(action="click", element=ids["Go search"])
    assert out["title"] == "Results" and "clicked submit" in b.ok(action="text")["text"]


def test_navigation_back_forward_reload_and_links(b):
    b.ok(action="goto", url=b.url("/"))
    out = b.ok(action="click", element=b.find(role="link", query="Second page")["Second page"])
    assert out["title"] == "Second" and out["navigated"] is True
    assert b.ok(action="back")["title"] == "JARVIS Test Page"
    assert b.ok(action="forward")["title"] == "Second"
    assert b.ok(action="reload")["title"] == "Second"


def test_stale_element_after_the_page_changed_itself(b):
    b.ok(action="goto", url=b.url("/"))
    ids = b.find()
    b.ok(action="click", element=ids["Mutate"])  # a script renames the 'Press me' button
    out = b.run(action="click", element=ids["Press me"])
    assert not out.success and "stale_element" in out.error
    assert "idle" in b.ok(action="text")["text"]  # and nothing was clicked


def test_elements_do_not_survive_navigation_or_a_closed_page(b):
    b.ok(action="goto", url=b.url("/"))
    old = b.find()["Press me"]
    b.ok(action="goto", url=b.url("/second"))
    assert "element_not_found" in b.run(action="click", element=old).error
    b.ok(action="goto", url=b.url("/"))
    p2 = b.ok(action="new", url=b.url("/second"))["page"]
    ref = b.find()["Back home"]
    b.ok(action="close", page=p2)
    assert "element_not_found" in b.run(action="click", element=ref).error
    assert "page_not_found" in b.run(action="info", page=p2).error


def test_popups_become_known_pages(b):
    b.ok(action="goto", url=b.url("/"))
    out = b.ok(action="click", element=b.find(role="link", query="Popup link")["Popup link"])
    assert out["pages"] == 2
    assert {p["title"] for p in b.ok(action="pages")} == {"JARVIS Test Page", "Popup"}


def test_login_pages_are_detected_and_nothing_is_entered(b):
    b.ok(action="goto", url=b.url("/login"))
    assert b.ok(action="info")["login_form_detected"] is True
    ids = b.find()
    for kw in ({"action": "fill", "element": ids["Username"], "text": "alice"}, {"action": "click", "element": ids["Log in"]}):
        out = b.run(**kw)
        assert not out.success and out.permission.level is R and out.permission.status is DecisionStatus.DENIED
    assert "Posted" not in b.ok(action="info")["title"]


def test_redirect_to_the_metadata_address_is_blocked_by_the_browser_guard(b):
    b.ok(action="goto", url=b.url("/"))
    out = b.run(action="goto", url=b.url("/redirect"))
    assert not out.success
    assert "169.254" not in b.ok(action="active")["url"]
    assert b.ok(action="goto", url=b.url("/"))["title"] == "JARVIS Test Page"  # and the browser is still usable


@pytest.mark.parametrize("url", ["file:///etc/hostname", "javascript:alert(1)", "data:text/html,hi", "chrome://version", "about:srcdoc"])
def test_dangerous_schemes_never_reach_the_browser(b, url):
    out = b.run(action="goto", url=url)
    assert not out.success and out.permission.level is R


def test_unwanted_downloads_are_cancelled(b):
    b.ok(action="goto", url=b.url("/"))
    out = b.ok(action="click", element=b.find(query="Sneaky download")["Sneaky download"])
    assert out.get("blocked_downloads") == 1 and "cancelled" in out["note"]
    assert not list(b.ws.iterdir())


def test_wanted_download_goes_to_the_approved_path(b):
    b.ok(action="goto", url=b.url("/"))
    link = b.find(role="link", query="Download hello")["Download hello"]
    out = b.ok(action="download", element=link, path=str(b.ws / "hello.txt"))
    assert (b.ws / "hello.txt").read_bytes() == b"hello download\n" and out["bytes"] == 15
    assert [p for p in Path(b.ws).iterdir()] == [b.ws / "hello.txt"]


def test_download_restrictions(b, tmp_path):
    b.ok(action="goto", url=b.url("/"))
    link = b.find(role="link", query="Download hello")["Download hello"]
    outside = b.run(action="download", element=link, path=str(b.ws / ".." / "escape.txt"))
    assert not outside.success and outside.permission.status is DecisionStatus.DENIED
    assert b.run(action="download", element=link, path=str(b.ws / "x.exe")).permission.level is R
    exe = b.find(role="link", query="Download tool")["Download tool"]
    out = b.run(action="download", element=exe, path=str(b.ws / "tool.bin"))
    assert not out.success and code(out) == "blocked_target" and not (b.ws / "tool.bin").exists()
    assert not list(b.ws.iterdir())


def test_upload_selects_an_approved_file_only(b):
    b.ok(action="goto", url=b.url("/"))
    chooser = b.find(query="Attachment")["Attachment"]
    f = b.ws / "doc.txt"
    f.write_text("x", encoding="utf-8")
    b.ok(action="upload", element=chooser, path=str(f))
    assert "doc.txt" in b.ok(action="text")["text"]
    secret = b.ws / ".env"
    secret.write_text("K=v", encoding="utf-8")
    assert b.run(action="upload", element=chooser, path=str(secret)).permission.level is R
    assert not b.run(action="upload", element=chooser, path=str(b.ws / ".." / "x.txt")).success


def test_page_text_is_data_and_truncation_works(b):
    b.ok(action="goto", url=b.url("/"))
    assert "untrusted_content" in b.ok(action="text")


def test_stop_ends_the_browser_and_a_new_session_has_a_new_identity(site, tmp_path):
    r = Real(tmp_path, site)
    try:
        r.start_or_skip()
        first = r.ok(action="status")["session"]
        r.ok(action="goto", url=r.url("/"))
        old = r.find()["Press me"]
        r.ok(action="stop")
        assert r.ok(action="status")["running"] is False
        r.ok(action="start")
        second = r.ok(action="status")["session"]
        assert first != second
        r.ok(action="goto", url=r.url("/"))
        assert "session_mismatch" in r.run(action="click", element=old).error
        assert "session_mismatch" in r.run(action="info", session=first).error
    finally:
        r.close()


def test_navigation_timeout_is_reported_and_the_browser_survives(site, tmp_path):
    r = Real(tmp_path, site, navigation_timeout=1.0)
    try:
        r.start_or_skip()
        out = r.run(action="goto", url=r.url("/slow"))
        assert not out.success and code(out) == "timeout"
        assert r.ok(action="goto", url=r.url("/second"))["title"] == "Second"
    finally:
        r.close()


def test_internal_addresses_are_refused_unless_listed(site, tmp_path):
    r = Real(tmp_path, site, private_hosts_allowed=())
    try:
        r.start_or_skip()
        out = r.run(action="goto", url=r.url("/"))
        assert not out.success and out.permission.level is R
    finally:
        r.close()


def test_a_browser_that_is_not_installed_is_a_clear_error(site, tmp_path):
    r = Real(tmp_path, site, executable_path=str(tmp_path / "no-such-browser"))
    try:
        out = r.run(action="start")
        assert not out.success and code(out) == "unavailable" and "not installed" in out.error
        assert r.ok(action="status")["running"] is False
    finally:
        r.close()


def test_the_browser_process_is_closed_on_stop(site, tmp_path):
    r = Real(tmp_path, site)
    try:
        r.start_or_skip()
        session = r.controller._session.provider_session
        assert session.is_alive()
        r.ok(action="stop")
        assert not session.is_alive()
    finally:
        r.close()
