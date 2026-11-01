"""Provider 'openai_compatible': POST {base_url}/chat/completions for Ollama, LM Studio, llama.cpp-server and similar (stdlib only).

Safe defaults: only loopback targets; a remote target needs `allow_remote = true`, https and an API key. The key comes from the
environment (resolved in config), is optional on loopback, is never put into error messages, repr or logs, and redirects are not followed.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from jarvis.errors import LLMError
from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse

log = logging.getLogger(__name__)

# (url, headers, body, timeout) -> (http_status, body_bytes); raises TimeoutError/OSError on transport failure.
Transport = Callable[[str, dict, bytes, float], "tuple[int, bytes]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never forward the key to another host
        return None


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    loopback = _is_loopback(urllib.parse.urlsplit(url).hostname or "")
    handlers: list = [_NoRedirect]
    if loopback:
        handlers.append(urllib.request.ProxyHandler({}))  # local servers are never reached through a proxy
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310 - scheme restricted by the provider
            return resp.status, resp.read(8_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(8_000)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, model: str, base_url: str | None, *, api_key: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 1024, timeout: float = 60.0, allow_remote: bool = False,
                 transport: Transport | None = None) -> None:
        if not base_url:
            raise LLMError("openai_compatible provider needs llm.base_url (e.g. http://127.0.0.1:11434/v1)")
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise LLMError("llm.base_url must be an http(s) URL with a host")
        if parts.username or parts.password:
            raise LLMError("llm.base_url must not contain credentials")
        self.is_remote = not _is_loopback(parts.hostname)
        if self.is_remote:
            if not allow_remote:
                raise LLMError("llm.base_url is not a loopback address; set llm.allow_remote = true to send data to a remote server")
            if parts.scheme != "https":
                raise LLMError("a remote llm.base_url must use https")
            if not api_key:
                raise LLMError("a remote llm.base_url needs an API key from the environment (JARVIS_LLM_API_KEY)")
        self._key = api_key or None
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._temp, self._max, self._timeout = temperature, max_tokens, timeout
        self._transport = transport or _urllib_transport

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(model={self._model!r}, url={self._url!r}, remote={self.is_remote})"

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model or self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": self._temp if request.temperature is None else request.temperature,
            "max_tokens": request.max_tokens or self._max,
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        log.debug("openai_compatible request to %s (remote=%s)", self._url, self.is_remote)
        try:
            status, raw = self._transport(self._url, headers, json.dumps(payload).encode(), self._timeout)
        except TimeoutError:
            raise LLMError(f"request to {self._url} timed out after {self._timeout:g}s") from None
        except OSError as exc:
            raise LLMError(self._scrub(f"request to {self._url} failed: {type(exc).__name__}: {exc}")) from None
        if status != 200:
            raise LLMError(self._scrub(f"HTTP {status} from {self._url}: {self._error_text(raw)}"))
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise LLMError(f"invalid (non-JSON) response from {self._url}") from None
        try:
            content = data["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise TypeError("content is not text")
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape from the openai_compatible server") from None
        usage = data.get("usage")
        return LLMResponse(content=content, model=str(data.get("model") or payload["model"]),
                           usage=usage if isinstance(usage, dict) else {}, raw=data)

    @staticmethod
    def _error_text(raw: bytes) -> str:
        text = raw.decode("utf-8", errors="replace")
        try:
            err = json.loads(text).get("error")
            text = str(err.get("message", err)) if isinstance(err, dict) else str(err if err is not None else text)
        except (ValueError, AttributeError):
            pass
        return text[:300]
