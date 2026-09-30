"""Binance Options adapter boundary.

The current Binance Options platform has a separate Options API. This module
will contain signing, demo endpoint selection, exchange-info validation,
market-data and order-state reconciliation. Live credentials are deliberately
not accepted by the initial engine.
"""
class BinanceOptionsDemo:
    def __init__(self, *args, **kwargs): self.enabled=False
    async def connect(self): raise NotImplementedError('Binance Options demo adapter is not enabled in phase 1')
