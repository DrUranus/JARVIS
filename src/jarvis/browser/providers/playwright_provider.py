"""Playwright provider (sync API on one dedicated worker thread).

This is the ONLY module that imports Playwright; it is imported lazily by the factory, so JARVIS starts without it.
Everything here runs inside the BrowserController's gate: nothing in this file decides what may happen, it only does
what the controller (after the permission engine) asks, plus two protections it enforces inside the browser engine:

* every request (navigation, redirect, sub-resource) is checked by the controller-supplied UrlGuard and aborted if refused;
* downloads nobody asked for are cancelled; wanted ones are written to a private temporary directory only.

The profile is a fresh, in-memory, non-persistent context: no saved cookies or logins exist, and this module never reads,
writes or exposes cookies, storage, headers or form values (page.evaluate runs only the fixed scripts below).
"""
from __future__ import annotations

import itertools
import os
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

from jarvis.browser.backend import BrowserPage, BrowserProvider, BrowserSession, UrlGuard
from jarvis.browser.errors import BrowserError, BrowserErrorCode, BrowserUnavailableError
from jarvis.browser.models import DownloadResult, ElementInfo, LaunchOptions, PageInfo, PageSnapshot

INTERACTIVE = ("a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], "
               "[role=checkbox], [role=radio], [role=textbox], [role=combobox], [role=menuitem], [role=tab], [role=switch]")

# One fixed script describes elements (all of them, or just index `one`). It never reads typed values: only whether a
# text field is non-empty, option LABELS of lists, and the label text of buttons.
DESCRIBE_JS = r"""
(a) => {
  const all = Array.from(document.querySelectorAll(a.sel));
  const forms = Array.from(document.forms);
  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && e.getAttribute('aria-hidden') !== 'true'; };
  const pwIn = (root) => Array.from(root.querySelectorAll('input[type=password]')).some(vis);
  const abs = (u) => { try { return new URL(u, document.baseURI).href; } catch (_) { return ''; } };
  const SENS = /pass(word)?\b|passwd|pwd|otp|cvv|cvc|card.?(num|no)|iban|ssn|secret|2fa|mfa|pin.?code/i;
  const name = (e) => {
    const al = e.getAttribute('aria-label'); if (al && txt(al)) return txt(al);
    const lb = e.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(n => n.textContent).join(' '); if (txt(t)) return txt(t); }
    if (e.labels && e.labels.length) { const t = Array.from(e.labels).map(l => l.textContent).join(' '); if (txt(t)) return txt(t); }
    const tag = e.tagName.toLowerCase();
    if (tag === 'input') { const ty = (e.type || '').toLowerCase();
      if (ty === 'submit' || ty === 'button' || ty === 'reset') return txt(e.value) || (ty === 'submit' ? 'Submit' : '');
      if (ty === 'image') return txt(e.alt) || txt(e.title);
      return txt(e.placeholder) || txt(e.title) || txt(e.name); }
    if (tag === 'textarea') return txt(e.placeholder) || txt(e.title) || txt(e.name);
    const t = txt(e.innerText || e.textContent); if (t) return t.slice(0, 200);
    const im = e.querySelector('img[alt]'); if (im && txt(im.alt)) return txt(im.alt);
    return txt(e.title);
  };
  const role = (e) => {
    const r = e.getAttribute('role'); if (r) return r.toLowerCase();
    const tag = e.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') { const ty = (e.type || 'text').toLowerCase();
      if (ty === 'checkbox' || ty === 'radio') return ty;
      if (['submit', 'button', 'reset', 'image'].includes(ty)) return 'button';
      if (ty === 'file') return 'file';
      return ty === 'search' ? 'searchbox' : 'textbox'; }
    return tag;
  };
  const one = (e, i) => {
    const tag = e.tagName.toLowerCase();
    const ty = tag === 'input' ? (e.type || 'text').toLowerCase() : (tag === 'button' ? (e.type || 'submit').toLowerCase() : '');
    const ac = (e.getAttribute('autocomplete') || '').toLowerCase();
    const field = tag === 'input' || tag === 'textarea';
    const sens = field && (ty === 'password' || /(^|\s)(cc-[a-z-]+|one-time-code|new-password|current-password)/.test(ac) ||
                           SENS.test((e.name || '') + ' ' + (e.id || '') + ' ' + (e.getAttribute('placeholder') || '')));
    const form = e.form || null;
    const fi = form ? forms.indexOf(form) : -1;
    const fa = e.getAttribute('formaction') || (form ? form.getAttribute('action') : null);
    const textlike = field && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'password'].includes(ty);
    return {
      locator: String(i), tag: tag, role: role(e), name: name(e), type: ty,
      href: tag === 'a' ? abs(e.getAttribute('href') || '') : '',
      dom_id: e.id || '', dom_name: e.getAttribute('name') || '',
      form: fi >= 0 ? fi : null,
      form_action: form || e.getAttribute('formaction') ? abs(fa === null || fa === '' ? location.href : fa) : '',
      visible: vis(e), enabled: !e.disabled && e.getAttribute('aria-disabled') !== 'true',
      checked: (ty === 'checkbox' || ty === 'radio') ? !!e.checked : null,
      has_value: textlike ? (e.value || '').length > 0 : false,
      options: tag === 'select' ? Array.from(e.options).slice(0, 60).map(o => txt(o.label || o.textContent)) : [],
      sensitive: !!sens, required: !!e.required,
      in_login_form: pwIn(form || document)
    };
  };
  if (a.one >= 0) { const e = all[a.one]; return e ? one(e, a.one) : null; }
  const out = [];
  for (let i = 0; i < all.length && out.length < a.max; i++) { if (vis(all[i])) out.push(one(all[i], i)); }
  const t = (document.body ? document.body.innerText : '') || '';
  return { elements: out, text: t.replace(/\n{3,}/g, '\n\n').slice(0, a.maxText + 1),
           forms: forms.length, password: Array.from(document.querySelectorAll('input[type=password]')).some(vis) };
}
"""


class _Worker:
    """All Playwright objects live on this one thread (the sync API is bound to the thread that created it)."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[Callable[[], Any], Future] | None]" = queue.Queue()
        self._t = threading.Thread(target=self._loop, name="jarvis-browser", daemon=True)
        self._t.start()

    def _loop(self) -> None:
        while (item := self._q.get()) is not None:
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn())
            except BaseException as exc:  # noqa: BLE001 - handed to the caller
                fut.set_exception(exc)

    def call(self, fn: Callable[[], Any], timeout: float = 120.0) -> Any:
        fut: Future = Future()
        self._q.put((fn, fut))
        try:
            return fut.result(timeout=timeout)
        except TimeoutError:
            raise
        except Exception:
            raise

    def stop(self) -> None:
        self._q.put(None)


def _translate(exc: BaseException) -> BrowserError:
    """Library errors become structured ones; messages are NOT forwarded (they can contain URLs and page content)."""
    if isinstance(exc, BrowserError):
        return exc
    name = type(exc).__name__
    text = str(exc)
    if name == "TimeoutError":
        return BrowserError(BrowserErrorCode.TIMEOUT, "the browser did not finish in time")
    if "ERR_BLOCKED_BY_CLIENT" in text:
        return BrowserError(BrowserErrorCode.BLOCKED_TARGET, "the request was blocked by the browser agent's URL policy")
    if "has been closed" in text or "Target closed" in text or "closed" in text.lower() and name == "TargetClosedError":
        return BrowserError(BrowserErrorCode.PAGE_NOT_FOUND, "the page or browser was closed")
    return BrowserError(BrowserErrorCode.BACKEND_ERROR, f"browser failure ({name})")


class PlaywrightPage(BrowserPage):
    def __init__(self, session: "PlaywrightSession", page: Any, key: str) -> None:
        self._s, self._page, self._key = session, page, key
        self._blocked = 0
        self._expecting = False
        page.on("download", self._on_download)

    def _on_download(self, download: Any) -> None:
        if self._expecting:
            return
        self._blocked += 1
        try:
            download.cancel()
        except Exception:  # noqa: BLE001
            pass

    def _do(self, fn: Callable[[], Any], timeout: float = 60.0) -> Any:
        def run() -> Any:
            try:
                return fn()
            except BaseException as exc:  # noqa: BLE001
                raise _translate(exc) from None
        return self._s.worker.call(run, timeout)

    @property
    def key(self) -> str:
        return self._key

    def info(self) -> PageInfo:
        def f() -> PageInfo:
            try:
                title = self._page.title()
            except Exception:  # noqa: BLE001 - mid-navigation
                title = ""
            return PageInfo(self._page.url, title)
        return self._do(f)

    def is_closed(self) -> bool:
        return bool(self._do(lambda: self._page.is_closed()))

    def goto(self, url: str, timeout: float) -> PageInfo:
        self._do(lambda: self._page.goto(url, timeout=timeout * 1000, wait_until="load"), timeout + 30)
        return self.info()

    def back(self, timeout: float) -> PageInfo:
        self._do(lambda: self._page.go_back(timeout=timeout * 1000, wait_until="load"), timeout + 30)
        return self.info()

    def forward(self, timeout: float) -> PageInfo:
        self._do(lambda: self._page.go_forward(timeout=timeout * 1000, wait_until="load"), timeout + 30)
        return self.info()

    def reload(self, timeout: float) -> PageInfo:
        self._do(lambda: self._page.reload(timeout=timeout * 1000, wait_until="load"), timeout + 30)
        return self.info()

    def bring_to_front(self) -> None:
        self._do(lambda: self._page.bring_to_front())

    @staticmethod
    def _info(d: dict[str, Any]) -> ElementInfo:
        return ElementInfo(
            locator=d["locator"], tag=d["tag"], role=d["role"], name=d["name"], type=d["type"], href=d["href"],
            dom_id=d["dom_id"], dom_name=d["dom_name"], form=d["form"], form_action=d["form_action"], visible=d["visible"],
            enabled=d["enabled"], checked=d["checked"], has_value=d["has_value"], options=tuple(d["options"]),
            sensitive=d["sensitive"], in_login_form=d["in_login_form"], required=d["required"])

    def snapshot(self, max_text: int, max_elements: int) -> PageSnapshot:
        def f() -> PageSnapshot:
            d = self._page.evaluate(DESCRIBE_JS, {"sel": INTERACTIVE, "one": -1, "max": max_elements, "maxText": max_text})
            text = d["text"]
            return PageSnapshot(PageInfo(self._page.url, self._page.title()), text[:max_text],
                                tuple(self._info(e) for e in d["elements"]), int(d["forms"]), bool(d["password"]),
                                len(text) > max_text)
        return self._do(f)

    def describe(self, locator: str) -> ElementInfo | None:
        idx = int(locator)

        def f() -> ElementInfo | None:
            d = self._page.evaluate(DESCRIBE_JS, {"sel": INTERACTIVE, "one": idx, "max": 1, "maxText": 0})
            return self._info(d) if d else None
        return self._do(f)

    def _loc(self, locator: str) -> Any:
        return self._page.locator(INTERACTIVE).nth(int(locator))

    def _settle(self) -> None:
        self._page.wait_for_timeout(120)  # lets popups / navigations started by the action arrive before we look

    def click(self, locator: str, timeout: float) -> None:
        def f() -> None:
            self._loc(locator).click(timeout=timeout * 1000)
            self._settle()
        self._do(f, timeout + 30)

    def fill(self, locator: str, text: str, timeout: float) -> None:
        self._do(lambda: self._loc(locator).fill(text, timeout=timeout * 1000), timeout + 30)

    def select(self, locator: str, option: str, timeout: float) -> None:
        def f() -> None:
            loc = self._loc(locator)
            try:
                loc.select_option(label=option, timeout=timeout * 1000)
            except Exception:  # noqa: BLE001 - not a label: try it as the option value
                loc.select_option(value=option, timeout=timeout * 1000)
        self._do(f, timeout + 30)

    def check(self, locator: str, checked: bool, timeout: float) -> None:
        self._do(lambda: self._loc(locator).set_checked(checked, timeout=timeout * 1000), timeout + 30)

    def submit(self, locator: str, timeout: float) -> None:
        def f() -> None:
            loc = self._loc(locator)
            d = self._page.evaluate(DESCRIBE_JS, {"sel": INTERACTIVE, "one": int(locator), "max": 1, "maxText": 0})
            if d and d["tag"] in ("input", "textarea", "select") and d["type"] not in ("submit", "button", "image", "reset"):
                loc.press("Enter", timeout=timeout * 1000)  # implicit form submission, exactly what a user would do
            else:
                loc.click(timeout=timeout * 1000)
            self._settle()
        self._do(f, timeout + 30)

    def set_file(self, locator: str, path: str, timeout: float) -> None:
        self._do(lambda: self._loc(locator).set_input_files(path, timeout=timeout * 1000), timeout + 30)

    def download(self, locator: str, directory: str, max_bytes: int, timeout: float) -> DownloadResult:
        def f() -> DownloadResult:
            self._expecting = True
            try:
                with self._page.expect_download(timeout=timeout * 1000) as info:
                    self._loc(locator).click(timeout=timeout * 1000)
                dl = info.value
                path = os.path.join(directory, f"download-{next(self._s.counter)}.part")
                dl.save_as(path)
                if dl.failure():
                    raise BrowserError(BrowserErrorCode.DOWNLOAD_FAILED, "the download failed")
                return DownloadResult(dl.suggested_filename or "download", os.path.getsize(path), path)
            finally:
                self._expecting = False
        return self._do(f, timeout + 60)

    def blocked_downloads(self) -> int:
        return self._blocked

    def close(self) -> None:
        self._do(lambda: self._page.close())


class PlaywrightSession(BrowserSession):
    def __init__(self, worker: _Worker, pw: Any, browser: Any, context: Any) -> None:
        self.worker, self._pw, self._browser, self._context = worker, pw, browser, context
        self.counter = itertools.count(1)
        self._wrapped: dict[int, PlaywrightPage] = {}
        self._closed = False

    def _wrap(self, page: Any) -> PlaywrightPage:
        w = self._wrapped.get(id(page))
        if w is None:
            w = self._wrapped[id(page)] = PlaywrightPage(self, page, f"pw{next(self.counter)}")
        return w

    def new_page(self) -> BrowserPage:
        return self.worker.call(lambda: self._wrap(self._context.new_page()))

    def pages(self) -> list[BrowserPage]:
        return self.worker.call(lambda: [self._wrap(p) for p in self._context.pages if not p.is_closed()])

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.worker.call(lambda: self._browser.is_connected(), 10))
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        def f() -> None:
            for step in (self._context.close, self._browser.close, self._pw.stop):
                try:
                    step()
                except Exception:  # noqa: BLE001 - keep closing
                    pass
        try:
            self.worker.call(f, 30)
        finally:
            self.worker.stop()


class PlaywrightProvider(BrowserProvider):
    name = "playwright"

    def start(self, options: LaunchOptions, guard: UrlGuard) -> BrowserSession:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailableError("the 'playwright' package is not installed "
                                          "(pip install -e \".[browser]\" and python -m playwright install chromium)") from None
        worker = _Worker()

        def launch() -> PlaywrightSession:
            pw = sync_playwright().start()
            browser = context = None
            try:
                kw: dict[str, Any] = {"headless": options.headless}
                if options.executable_path:
                    kw["executable_path"] = options.executable_path
                elif options.browser in ("chrome", "msedge"):
                    kw["channel"] = options.browser
                try:
                    browser = pw.chromium.launch(**kw)
                except Exception as exc:  # noqa: BLE001
                    text = str(exc).lower()
                    if any(m in text for m in ("executable doesn't exist", "playwright install", "is not found", "not found at",
                                               "no such file", "failed to launch")) and "sandbox" not in text:
                        raise BrowserUnavailableError(
                            "the browser is not installed (python -m playwright install chromium, or set browser.browser = "
                            "\"msedge\"/\"chrome\" or browser.executable_path)") from None
                    raise
                context = browser.new_context(
                    viewport={"width": options.viewport[0], "height": options.viewport[1]}, accept_downloads=True,
                    service_workers="block", ignore_https_errors=False, java_script_enabled=True)
                context.set_default_timeout(options.action_timeout * 1000)
                context.set_default_navigation_timeout(options.navigation_timeout * 1000)

                def route(r: Any) -> None:
                    req = r.request
                    try:
                        ok = guard(req.url, bool(req.is_navigation_request()))
                    except Exception:  # noqa: BLE001 - a broken guard refuses
                        ok = False
                    if ok:
                        r.continue_()
                    else:
                        r.abort("blockedbyclient")

                context.route("**/*", route)

                def route_ws(ws: Any) -> None:
                    # WebSockets are not covered by route(): apply the same URL policy (ws -> http, wss -> https)
                    url = ws.url
                    http = ("https" + url[3:]) if url.startswith("wss:") else ("http" + url[2:]) if url.startswith("ws:") else url
                    try:
                        ok = guard(http, False)
                    except Exception:  # noqa: BLE001
                        ok = False
                    if ok:
                        ws.connect_to_server()
                    else:
                        ws.close()

                context.route_web_socket("**/*", route_ws)
                return PlaywrightSession(worker, pw, browser, context)
            except BaseException:
                for obj in (context, browser):
                    try:
                        if obj is not None:
                            obj.close()
                    except Exception:  # noqa: BLE001
                        pass
                pw.stop()
                raise

        try:
            return worker.call(launch, 90)
        except BrowserError:
            worker.stop()
            raise
        except BaseException as exc:
            worker.stop()
            raise _translate(exc) from None
