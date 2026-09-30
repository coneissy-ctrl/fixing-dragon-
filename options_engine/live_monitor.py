"""Continuous Deriv live-data monitor with a read-only dashboard.

This process observes live ticks, builds completed 1m/5m candles and evaluates
the existing strategy. It never buys a contract. Demo execution remains a
separate explicitly gated action.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from .adapters.deriv import DerivOptionsDemo, DerivAdapterError
from .candles import CandleAggregator
from .strategy import BinaryStrategy
from .dashboard import DashboardState, serve_dashboard


class LiveMonitor:
    def __init__(self, symbol: str | None = None):
        self.symbol = symbol or os.getenv("DERIV_SYMBOL", "1HZ100V")
        self.adapter = DerivOptionsDemo(timeout=float(os.getenv("DERIV_WS_TIMEOUT", "12")))
        self.state = DashboardState(symbol=self.symbol)
        self.aggregators = {1: CandleAggregator(1), 5: CandleAggregator(5)}
        self.strategies = {1: BinaryStrategy(1), 5: BinaryStrategy(5)}
        self.candles: dict[int, list[Any]] = {1: [], 5: []}
        self.stakes = {1: Decimal("0.5"), 5: Decimal("2")}

    async def run(self) -> None:
        self.state.status = "CONNECTING"
        await self.adapter.connect_market_data()
        # Authenticate to the selected account for read-only verification.
        # submit() remains separately gated when real trading is disabled.
        await self.adapter.connect_account()
        symbols = await self.adapter.active_symbols()
        available = {str(x.get("underlying_symbol") or x.get("symbol")) for x in symbols if x.get("underlying_symbol") or x.get("symbol")}
        candidates = [self.symbol, "1HZ100V", "1HZ10V", "1HZ25V", "R_100", "R_75", "R_50", "R_25", "R_10"]
        selected = None
        for candidate in candidates:
            if candidate not in available:
                continue
            try:
                await self.adapter.contracts_for(candidate)
                selected = candidate
                break
            except DerivAdapterError:
                continue
        if selected is None:
            raise RuntimeError("No supported tick symbol found in Deriv active_symbols")
        self.symbol = selected
        self.state.symbol = self.symbol
        self.state.status = (
            "LIVE_ACCOUNT_CONNECTED" if self.adapter.account_mode == "real"
            else "DEMO_ACCOUNT_CONNECTED"
        )
        self.state.connected_at = time.time()
        async for tick in self.adapter.ticks(self.symbol):
            self.state.tick_count += 1
            self.state.last_tick = asdict(tick)
            self.state.last_tick_at = time.time()
            self.state.quote = str(tick.quote)
            for tf, agg in self.aggregators.items():
                completed = agg.update(tick.epoch, float(tick.quote))
                if completed is None:
                    continue
                self.candles[tf].append(completed)
                self.candles[tf] = self.candles[tf][-80:]
                self.state.candles[tf] += 1
                signal = self.strategies[tf].generate(self.symbol, self.candles[tf], self.stakes[tf])
                if signal:
                    self.state.signals[tf] += 1
                    self.state.last_signals[tf] = {
                        "direction": signal.direction,
                        "stake": str(signal.stake),
                        "confidence": str(signal.confidence),
                        "expiry_seconds": signal.expiry_seconds,
                        "candle_timestamp": signal.candle_timestamp,
                        "reason": signal.reason,
                    }
            self.state.updated_at = time.time()

    async def close(self) -> None:
        await self.adapter.close()


async def main() -> None:
    monitor = LiveMonitor()
    dashboard_server = await serve_dashboard(monitor.state)
    print(
        f"DASHBOARD_LISTENING host={os.getenv('DASHBOARD_HOST', '0.0.0.0')} "
        f"port={os.getenv('PORT', '10000')}",
        flush=True,
    )
    try:
        while True:
            try:
                await monitor.run()
            except Exception as exc:
                monitor.state.status = "DATA_ERROR"
                monitor.state.updated_at = time.time()
                monitor.state.last_signals[0] = {"error": str(exc)}
                await monitor.close()
                await asyncio.sleep(5)
    finally:
        dashboard_server.close()
        await dashboard_server.wait_closed()
        await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
