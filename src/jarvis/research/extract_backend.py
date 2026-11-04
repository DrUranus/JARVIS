"""HTML-to-text extraction backends for the research layer (data in, plain text out; no network, no tools, nothing is executed).

Default: "builtin" (standard library only). Optional: "trafilatura" (extra `research`, imported lazily in the factory only; a missing library gives a
clear ResearchError instead of a crash). Input and output are bounded; the text is DATA - an instruction inside a page is just text."""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Callable

from jarvis.research.errors import ResearchError

DEFAULT_BACKEND = "builtin"
BACKENDS = ("builtin", "trafilatura")
DEFAULT_MAX_INPUT_CHARS = 500_000
DEFAULT_MAX_OUTPUT_CHARS = 30_000
HARD_MAX_INPUT_CHARS = 2_000_000
HARD_MAX_OUTPUT_CHARS = 200_000
_SKIP = frozenset({"script", "style", "noscript", "template", "nav", "header", "footer", "aside", "form", "svg", "iframe", "head", "button", "select", "object", "embed"})
_BLOCK = frozenset({"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "main", "blockquote", "pre", "td", "th", "dd", "dt"})
Extractor = Callable[[str], str]


def _check_limits(max_input_chars: int, max_output_chars: int) -> None:
    if not isinstance(max_input_chars, int) or not 1 <= max_input_chars <= HARD_MAX_INPUT_CHARS:
        raise ResearchError(f"max_input_chars must be 1..{HARD_MAX_INPUT_CHARS}")
    if not isinstance(max_output_chars, int) or not 1 <= max_output_chars <= HARD_MAX_OUTPUT_CHARS:
        raise ResearchError(f"max_output_chars must be 1..{HARD_MAX_OUTPUT_CHARS}")


def _check_halt(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise ResearchError("extraction cancelled (halt)")


class _TextParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.size = 0
        self.limit = limit
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK and not self.skip:
            self._add("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK and not self.skip:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK and not self.skip:
            self._add("\n")

    def handle_data(self, data):
        if not self.skip:
            self._add(data)

    def _add(self, s: str) -> None:
        if self.size < self.limit:
            self.parts.append(s)
            self.size += len(s)


def _normalise(text: str, limit: int) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(l for l in lines if l)[:limit]


def html_to_text(html: str, *, max_input_chars: int = DEFAULT_MAX_INPUT_CHARS, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
                 is_cancelled: Callable[[], bool] | None = None) -> str:
    """Builtin backend: visible text of the HTML without script/style/navigation/footer parts. Tolerates broken HTML."""
    _check_halt(is_cancelled)
    _check_limits(max_input_chars, max_output_chars)
    if not isinstance(html, str):
        raise ResearchError("html must be a string")
    parser = _TextParser(max_output_chars * 2)
    try:
        parser.feed(html[:max_input_chars])
        parser.close()
    except Exception:                                       # broken markup must not crash the research task: keep what was read
        pass
    return _normalise("".join(parser.parts), max_output_chars)


def make_extractor(backend: str = DEFAULT_BACKEND, *, max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
                   max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS, is_cancelled: Callable[[], bool] | None = None) -> Extractor:
    """Factory. `trafilatura` is imported only here; if it is not installed a ResearchError names the extra."""
    _check_limits(max_input_chars, max_output_chars)
    if backend == "builtin":
        return lambda html: html_to_text(html, max_input_chars=max_input_chars, max_output_chars=max_output_chars, is_cancelled=is_cancelled)
    if backend != "trafilatura":
        raise ResearchError(f"unknown extraction backend {backend!r}; choose one of {', '.join(BACKENDS)}")
    try:
        import trafilatura                                    # lazy: optional extra
    except ImportError as exc:
        raise ResearchError("extraction backend 'trafilatura' is not installed; install the optional extra 'research' (or use the default 'builtin')") from exc

    def extract(html: str) -> str:
        _check_halt(is_cancelled)
        if not isinstance(html, str):
            raise ResearchError("html must be a string")
        try:
            out = trafilatura.extract(html[:max_input_chars], include_comments=False, include_tables=True, include_links=False, favor_precision=True)
        except Exception as exc:
            raise ResearchError(f"extraction failed: {type(exc).__name__}") from exc
        return _normalise(out or "", max_output_chars)

    return extract
