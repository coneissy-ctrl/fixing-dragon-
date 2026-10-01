"""Network smoke test for Deriv public live market data.

No credentials and no trading. The test only verifies that the public Options
WebSocket can return active symbols and one live tick.
"""
from __future__ import annotations

import asyncio
import os

from .adapters.deriv import DerivOptionsDemo


async def run(symbol: str | None = None) -> int:
    adapter = DerivOptionsDemo(timeout=12)
    await adapter.connect_market_data()
    try:
        symbols = await adapter.active_symbols()
        if not symbols:
            raise RuntimeError("Deriv returned no active symbols")
        requested = symbol or os.getenv("DERIV_SYMBOL", "R_100")
        available = {str(x.get("underlying_symbol") or x.get("symbol")) for x in symbols if x.get("underlying_symbol") or x.get("symbol")}
        target = requested if requested in available else next(iter(available))
        tick = await anext(adapter.ticks(target))
        if tick.quote <= 0 or tick.epoch <= 0:
            raise RuntimeError(f"invalid live tick: {tick}")
        print(f"DERIV_LIVE_DATA_OK symbol={tick.symbol} quote={tick.quote} epoch={tick.epoch}")
        return 0
    finally:
        await adapter.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
