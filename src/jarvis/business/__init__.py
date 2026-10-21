"""Business v1: structured, labelled business analyses (market, competitors, business plan, business data, marketing drafts, lead preparation) from research
results and given numbers. No tools, no sending, no publishing. The Core does not import it; `bootstrap` builds it (opt-in)."""
from jarvis.business.errors import BusinessError, InvalidBusinessInput
from jarvis.business.models import Assumption, Basis, BusinessResult, Competitor, Entry

__all__ = ["Assumption", "Basis", "BusinessResult", "Competitor", "Entry", "BusinessError", "InvalidBusinessInput"]
