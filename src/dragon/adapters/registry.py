from __future__ import annotations
from .base import QuoteAdapter, AdapterResult

class IsolatedAdapterRegistry:
    """Calls adapters independently; an adapter failure is data, not a global failure."""

    def __init__(self, adapters: list[QuoteAdapter]):
        venues = [a.venue for a in adapters]
        if len(venues) != len(set(venues)):
            raise ValueError("duplicate venue adapter")
        self.adapters = tuple(adapters)

    def quote_all(self, request):
        return tuple(adapter.safe_quote(request) for adapter in self.adapters)

    def by_venue(self, venue):
        for adapter in self.adapters:
            if adapter.venue == venue:
                return adapter
        raise KeyError(venue)
