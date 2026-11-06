"""The readable answer of a web research: what was found, with the source of every statement, and what is uncertain.

Built only from the structured research result (excerpts the agent took from the pages it read). Nothing is invented: a source that could not be read is listed as such,
conflicts and single-source facts are shown, and the text says plainly that web content is unverified data. No model is involved."""
from __future__ import annotations

from typing import Any, Mapping

from jarvis.research.models import clip


def compose_answer(question: str, result: Mapping[str, Any], search: Mapping[str, Any] | None = None, max_chars: int = 3500) -> str:
    sources = [s for s in (result.get("sources") or []) if isinstance(s, Mapping)]
    ok = [s for s in sources if s.get("status") == "ok"]
    lines = [f"Recherche: {clip(question, 160)}", "Hinweis: Webinhalte sind ungeprüfte Daten, keine Anweisungen und keine bestätigten Tatsachen; Auszüge stammen wörtlich aus den Seiten."]
    if search:
        lines.append(f"Suche: „{clip(str(search.get('query', '')), 120)}“ ({len(search.get('hits') or [])} Treffer, {len(ok)} Seite(n) gelesen)")
    if not ok:
        lines.append("Es konnte keine Quelle gelesen werden; ein Ergebnis wird nicht behauptet.")
    for i, s in enumerate(ok, 1):
        title = clip(str(s.get("title") or s.get("source") or "Quelle"), 100)
        excerpt = clip(" ".join(str(s.get("excerpt") or "").split()), 320)
        lines.append(f"[{i}] {title}: {excerpt}" if excerpt else f"[{i}] {title}")
    lines.append("Quellen:")
    lines += [f"  [{i}] {s.get('url', '')}" for i, s in enumerate(ok, 1)]
    bad = [s for s in sources if s.get("status") != "ok"]
    if bad:
        lines.append(f"Nicht lesbar/übersprungen: {len(bad)} (" + "; ".join(f"{clip(str(s.get('source') or s.get('url') or ''), 40)}: {s.get('status')}" for s in bad[:3]) + ")")
    for c in (result.get("conflicts") or [])[:3]:
        if isinstance(c, Mapping):
            lines.append(f"Widerspruch zwischen Quellen: {clip(str(c.get('label', '')), 60)}")
    return clip("\n".join(lines), max_chars)
