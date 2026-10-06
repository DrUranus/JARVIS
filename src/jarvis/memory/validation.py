"""Input normalisation shared by every backend. Raises MemoryValidationError on bad input."""
from __future__ import annotations

import json
from typing import Any, Iterable

from jarvis.errors import MemoryValidationError
from jarvis.memory.models import IMPORTANCE_MAX, IMPORTANCE_MIN, MemoryType

MAX_CONTENT_LENGTH = 10_000   # hard ceiling; the configured limit may only be lower
MAX_TAGS, MAX_TAG_LENGTH = 20, 50
MAX_SOURCE_LENGTH = 200
MAX_METADATA_JSON = 4096
MAX_LIMIT = 1000


def normalize_content(content: Any, max_length: int = MAX_CONTENT_LENGTH) -> str:
    if not isinstance(content, str):
        raise MemoryValidationError("memory content must be a string")
    text = content.strip()
    if not text:
        raise MemoryValidationError("memory content must not be empty")
    if len(text) > min(max_length, MAX_CONTENT_LENGTH):
        raise MemoryValidationError(f"memory content too long ({len(text)} > {min(max_length, MAX_CONTENT_LENGTH)} characters)")
    return text


def normalize_type(value: Any) -> MemoryType:
    if isinstance(value, MemoryType):
        return value
    if isinstance(value, str):
        try:
            return MemoryType(value.strip().lower())
        except ValueError:
            pass
    raise MemoryValidationError(f"invalid memory type {value!r}; valid: {[t.value for t in MemoryType]}")


def normalize_importance(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not IMPORTANCE_MIN <= value <= IMPORTANCE_MAX:
        raise MemoryValidationError(f"importance must be an integer {IMPORTANCE_MIN}..{IMPORTANCE_MAX}")
    return value


def normalize_tags(tags: Iterable[str] | None) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, (str, bytes)) or not hasattr(tags, "__iter__"):
        raise MemoryValidationError("tags must be a list of strings")
    out: list[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            raise MemoryValidationError("each tag must be a non-empty string")
        t = tag.strip().casefold()
        if len(t) > MAX_TAG_LENGTH:
            raise MemoryValidationError(f"tag too long (max {MAX_TAG_LENGTH})")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise MemoryValidationError(f"too many tags (max {MAX_TAGS})")
    return tuple(out)


def normalize_source(source: Any) -> str | None:
    if source is None:
        return None
    if not isinstance(source, str) or len(source) > MAX_SOURCE_LENGTH:
        raise MemoryValidationError(f"source must be a string of at most {MAX_SOURCE_LENGTH} characters")
    return source.strip() or None


def normalize_metadata(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict) or not all(isinstance(k, str) for k in metadata):
        raise MemoryValidationError("metadata must be a dict with string keys")
    try:
        encoded = json.dumps(metadata, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(f"metadata must be JSON-serialisable: {exc}") from exc
    if len(encoded) > MAX_METADATA_JSON:
        raise MemoryValidationError(f"metadata too large (max {MAX_METADATA_JSON} characters as JSON)")
    return json.loads(encoded)  # detached deep copy


def normalize_limit(limit: Any, default: int | None = None) -> int:
    if limit is None and default is not None:
        return default
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise MemoryValidationError("limit must be a non-negative integer")
    return min(limit, MAX_LIMIT)


def normalize_query(query: Any) -> str:
    if not isinstance(query, str):
        raise MemoryValidationError("search query must be a string")
    return query
