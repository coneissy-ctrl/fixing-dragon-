"""Continuous Deriv live-data monitor with a read-only dashboard.

This process observes live ticks, builds completed 1m/5m candles and evaluates
the existing strategy. It never buys a contract. Demo execution remains a
separate explicitly gated action.
"""
from __future__ import annotations

import asyncio
import os
import time
import base64
import hashlib
import secrets
from urllib.parse import urlencode
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
        self.oauth_client_id = os.getenv("DERIV_CLIENT_ID")
        self.oauth_redirect_uri = os.getenv(
            "DERIV_REDIRECT_URI",
            "https://dragon-options-demo-dashboard.onrender.com/oauth/deriv/callback",
        )
        self.oauth_states: dict[str, str] = {}

    def oauth_login_url(self) -> str:
        if not self.oauth_client_id:
            raise DerivAdapterError("DERIV_CLIENT_ID is not configured")
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.oauth_states[state] = verifier
        params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "redirect_uri": self.oauth_redirect_uri,
            "scope": "trade",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return "https://auth.deriv.com/oauth2/auth?" + urlencode(params)

    async def oauth_callback(self, code: str, state: str) -> None:
        verifier = self.oauth_states.pop(state, None)
        if not verifier:
            raise DerivAdapterError("OAuth state mismatch or expired")
        if not self.oauth_client_id:
            raise DerivAdapterError("DERIV_CLIENT_ID is not configured")
        async with httpx.AsyncClient(timeout=self.adapter.timeout) as client:
            response = await client.post(
                "https://auth.deriv.com/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.oauth_client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": self.oauth_redirect_uri,
                },
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise DerivAdapterError("Deriv OAuth token response did not contain access_token")
        await self.adapter.set_oauth_token(token)
        await self.adapter.connect_account()
        print(
            f"DERIV_OAUTH authenticated account_id_present={bool(self.adapter.account_id)} "
            f"live_execution_enabled={self.adapter.live_trading_enabled}",
            flush=True,
        )
        self.state.status = "AUTHENTICATED_READ_ONLY"

    async def run(self) -> None:
        self.state.status = "CONNECTING"
        print("DERIV_CONNECT market_data", flush=True)
        await self.adapter.connect_market_data()
        if self.adapter.auth_token and self.adapter.account_id:
            print(
                f"DERIV_CONNECT account mode={self.adapter.account_mode} "
                f"live_execution_enabled={self.adapter.live_trading_enabled}",
                flush=True,
            )
            await self.adapter.connect_account()
            print("DERIV_CONNECT account_connected", flush=True)
        else:
            print("DERIV_CONNECT account waiting_for_oauth", flush=True)
        symbols = await self.adapter.active_symbols()
        print(f"DERIV_SYMBOLS received={len(symbols)}", flush=True)
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
            raise RuntimeError(
                "No supported tick symbol found in Deriv active_symbols "
                f"(requested={self.symbol}, received={len(available)})"
            )
        print(f"DERIV_SYMBOL selected={selected}", flush=True)
        print("DERIV_TICKS subscription_start", flush=True)
        self.symbol = selected
        self.state.symbol = self.symbol
        self.state.status = (
            "LIVE_ACCOUNT_CONNECTED" if self.adapter.account_mode == "real"
            else "DEMO_ACCOUNT_CONNECTED"
        )
        self.state.connected_at = time.time()
        async for tick in self.adapter.ticks(self.symbol):
            if self.state.tick_count == 0:
                print(f"DERIV_TICKS first_tick symbol={self.symbol}", flush=True)
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
    dashboard_server = await serve_dashboard(
        monitor.state, monitor.oauth_login_url, monitor.oauth_callback
    )
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
                print(
                    f"DERIV_MONITOR_ERROR type={type(exc).__name__} error={exc}",
                    flush=True,
                )
                await monitor.close()
                await asyncio.sleep(5)
    finally:
        dashboard_server.close()
        await dashboard_server.wait_closed()
        await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
