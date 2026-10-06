"""OpenAI and Anthropic providers over plain HTTPS (no SDK dependency)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from jarvis.errors import LLMError
from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse, Role


def _post(url: str, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} from {url}: {exc.read().decode(errors='replace')[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise LLMError(f"request to {url} failed: {exc}") from exc


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, model: str, base_url: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 1024, timeout: float = 60.0) -> None:
        if not api_key:
            raise LLMError("OpenAI provider needs OPENAI_API_KEY (or JARVIS_LLM_API_KEY)")
        self._key, self._model = api_key, model
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self._temp, self._max, self._timeout = temperature, max_tokens, timeout

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model or self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": self._temp if request.temperature is None else request.temperature,
            "max_tokens": request.max_tokens or self._max,
        }
        data = _post(self._url, {"Authorization": f"Bearer {self._key}"}, payload, self._timeout)
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected OpenAI response shape: {str(data)[:200]}") from exc
        return LLMResponse(content=content, model=data.get("model", payload["model"]),
                           usage=data.get("usage", {}), raw=data)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str, base_url: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 1024, timeout: float = 60.0) -> None:
        if not api_key:
            raise LLMError("Anthropic provider needs ANTHROPIC_API_KEY (or JARVIS_LLM_API_KEY)")
        self._key, self._model = api_key, model
        self._url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        self._temp, self._max, self._timeout = temperature, max_tokens, timeout

    def complete(self, request: LLMRequest) -> LLMResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role is Role.SYSTEM)
        payload: dict = {
            "model": request.model or self._model,
            "messages": [{"role": m.role.value, "content": m.content}
                         for m in request.messages if m.role is not Role.SYSTEM],
            "temperature": self._temp if request.temperature is None else request.temperature,
            "max_tokens": request.max_tokens or self._max,
        }
        if system:
            payload["system"] = system
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        data = _post(self._url, headers, payload, self._timeout)
        try:
            content = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError, AttributeError) as exc:
            raise LLMError(f"unexpected Anthropic response shape: {str(data)[:200]}") from exc
        return LLMResponse(content=content, model=data.get("model", payload["model"]),
                           usage=data.get("usage", {}), raw=data)
