from .base import QuoteAdapter

class SushiSwapAdapter(QuoteAdapter):
    venue = "sushiswap"

    def __init__(self, quote_fn):
        self._quote_fn = quote_fn

    def quote(self, request):
        return self._quote_fn(request)
