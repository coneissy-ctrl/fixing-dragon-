"""Continuous Deriv live-data monitor with OAuth account connection and dashboard."""
from __future__ import annotations

import asyncio
import os
import time
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from .adapters.deriv import DerivOptionsDemo, DerivAdapterError, DERIV_MCP_URL
from .candles import CandleAggregator
from .strategy import BinaryStrategy
from .dashboard import DashboardState, serve_dashboard
from .analytics import AmplitudeAnalytics


class LiveMonitor:
    def __init__(self, symbol: str | None = None):
        self.symbol = symbol or "frxXAUUSD"
        self.adapter = DerivOptionsDemo(timeout=float(os.getenv("DERIV_WS_TIMEOUT", "12")))
        self.state = DashboardState(
            symbol=self.symbol,
            account_mode=self.adapter.account_mode,
            live_execution_enabled=self.adapter.live_trading_enabled,
        )
        self.aggregators = {1: CandleAggregator(1), 5: CandleAggregator(5)}
        self.strategies = {1: BinaryStrategy(1), 5: BinaryStrategy(5)}
        self.candles: dict[int, list[Any]] = {1: [], 5: []}
        self.stakes = {1: Decimal("0.5"), 5: Decimal("2")}
        self.oauth_client_id = os.getenv("DERIV_CLIENT_ID")
        self.oauth_redirect_uri = os.getenv(
            "DERIV_REDIRECT_URI",
            "https://deriveonlyrender.onrender.com/oauth/deriv/callback",
        )
        # state -> (PKCE verifier, created_at, validated return URL)
        self.oauth_states: dict[str, tuple[str, float, str]] = {}
        self.oauth_scopes: list[str] = []
        self.oauth_expires_at: str | None = None
        self.oauth_return_url: str | None = None
        self.balance_task: asyncio.Task | None = None
        self.execution_lock = asyncio.Lock()
        self.last_execution_at = 0.0
        self.min_balance_buffer = Decimal(os.getenv("DERIV_MIN_BALANCE_BUFFER", "0"))
        self.auto_execute = os.getenv("DERIV_AUTO_EXECUTE", "true").lower() == "true"
        self.analytics = AmplitudeAnalytics()
        self.analytics.start()

    def _sync_account_state(self) -> None:
        self.state.account_id = self.adapter.account_id
        self.state.account_mode = self.adapter.account_mode
        self.state.live_execution_enabled = self.adapter.live_trading_enabled

    def _validate_oauth_return_url(self, return_to: str | None) -> str:
        default = os.getenv(
            "DERIV_OAUTH_RETURN_URL",
            "https://deriveonlyrender.onrender.com/",
        )
        candidate = (return_to or default).strip()
        allowed = [
            x.strip().rstrip("/")
            for x in os.getenv("DERIV_OAUTH_ALLOWED_RETURN_ORIGINS", "").split(",")
            if x.strip()
        ]
        if not allowed:
            allowed = [
                "https://deriveonlyrender.onrender.com",
            ]
        try:
            parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(candidate)
        except Exception as exc:
            raise DerivAdapterError("Invalid OAuth return URL") from exc
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme != "https" or origin.rstrip("/") not in allowed:
            raise DerivAdapterError("OAuth return URL is not allowlisted")
        return candidate

    def oauth_login_url(self, return_to: str | None = None) -> str:
        if not self.oauth_client_id:
            raise DerivAdapterError("DERIV_CLIENT_ID is not configured")
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        now = time.time()
        self.oauth_states = {
            k: v for k, v in self.oauth_states.items() if now - v[1] < 600
        }
        validated_return = self._validate_oauth_return_url(return_to)
        self.oauth_states[state] = (verifier, now, validated_return)
        self.oauth_return_url = validated_return
        params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "redirect_uri": self.oauth_redirect_uri,
            "scope": os.getenv("DERIV_OAUTH_SCOPE", "trade"),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return "https://auth.deriv.com/oauth2/auth?" + urlencode(params)

    async def _execute_signal(self, signal: Any) -> None:
        if not self.auto_execute:
            return
        if self.adapter.account_mode != "real" or not self.adapter.live_trading_enabled:
            return
        if self.state.status != "LIVE_ACCOUNT_CONNECTED" or not self.adapter.connected:
            return
        async with self.execution_lock:
            now = time.time()
            min_interval = float(os.getenv("DERIV_MIN_EXECUTION_INTERVAL", "30"))
            if now - self.last_execution_at < min_interval:
                return
            try:
                balance = await self.adapter.balance()
                if balance <= signal.stake + self.min_balance_buffer:
                    raise DerivAdapterError("insufficient balance for configured stake")
                order = await self.adapter.submit(
                    signal.symbol,
                    signal.direction,
                    signal.stake,
                    duration_seconds=signal.expiry_seconds,
                )
                self.last_execution_at = now
                self.analytics.track(
                    "deriv_option_executed",
                    event_properties={
                        "symbol": signal.symbol,
                        "direction": signal.direction,
                        "stake": float(signal.stake),
                        "expiry_seconds": signal.expiry_seconds,
                        "timeframe_minutes": signal.timeframe_minutes,
                        "confidence": float(signal.confidence),
                        "contract_id_present": bool(order.get("contract_id")),
                    },
                )
                self.state.last_signals[signal.timeframe_minutes]["execution"] = order
                print(f"DERIV_AUTO_EXECUTED contract_id={order.get('contract_id')} symbol={signal.symbol} direction={signal.direction} stake={signal.stake} expiry={signal.expiry_seconds}s", flush=True)
                await self._refresh_balance()
            except Exception as exc:
                self.state.last_signals[signal.timeframe_minutes]["execution_error"] = f"{type(exc).__name__}: {exc}"
                print(f"DERIV_AUTO_EXECUTION_ERROR type={type(exc).__name__} error={exc}", flush=True)

    async def _refresh_balance(self) -> None:
        try:
            value = await self.adapter.balance()
            self.state.balance = str(value)
            self.state.balance_updated_at = time.time()
            self.state.balance_error = None
        except Exception as exc:
            self.state.balance_error = f"{type(exc).__name__}: {exc}"
            print(f"DERIV_BALANCE_ERROR type={type(exc).__name__} error={exc}", flush=True)

    async def _balance_loop(self) -> None:
        while True:
            await self._refresh_balance()
            await asyncio.sleep(float(os.getenv("DERIV_BALANCE_POLL_SECONDS", "5")))

    def _start_balance_loop(self) -> None:
        if self.balance_task is None or self.balance_task.done():
            self.balance_task = asyncio.create_task(self._balance_loop())

    async def oauth_callback(self, code: str, state: str) -> None:
        entry = self.oauth_states.pop(state, None)
        if not entry:
            raise DerivAdapterError("OAuth state mismatch or expired")
        verifier, created_at, return_to = entry
        if time.time() - created_at >= 600:
            raise DerivAdapterError("OAuth state expired")
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
        if response.is_error:
            try:
                payload = response.json()
                error = payload.get("error") or payload.get("error_description")
            except Exception:
                error = response.text[:300]
            raise DerivAdapterError(
                f"Deriv OAuth token exchange HTTP {response.status_code}: {error}"
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise DerivAdapterError("Deriv OAuth token response did not contain access_token")

        self.oauth_scopes = [str(x) for x in (payload.get("scope") or os.getenv("DERIV_OAUTH_SCOPE", "trade").split())] if isinstance(payload.get("scope") or "", (list, str)) else [os.getenv("DERIV_OAUTH_SCOPE", "trade")]
        expires_in = payload.get("expires_in")
        self.oauth_expires_at = str(time.time() + float(expires_in)) if expires_in else None
        scope_value = payload.get("scope")
        self.oauth_scopes = scope_value.split() if isinstance(scope_value, str) else [os.getenv("DERIV_OAUTH_SCOPE", "trade")]
        expires_in = payload.get("expires_in")
        self.oauth_expires_at = str(time.time() + float(expires_in)) if expires_in else None
        await self.adapter.set_oauth_token(token)
        await self.adapter.connect_account()
        self._sync_account_state()
        self.oauth_return_url = return_to
        self.state.status = "LIVE_ACCOUNT_CONNECTED" if self.adapter.connected else "AUTHENTICATED_READ_ONLY"
        self.state.updated_at = time.time()
        self._start_balance_loop()
        print(
            f"DERIV_OAUTH authenticated account_id_present={bool(self.adapter.account_id)} "
            f"mode={self.adapter.account_mode} live_execution_enabled={self.adapter.live_trading_enabled} "
            f"mcp_context={self.adapter.mcp_url}",
            flush=True,
        )

    def oauth_status(self) -> dict[str, Any]:
        authenticated = bool(self.adapter.oauth_authenticated and self.adapter.account_id)
        return {
            "connected": authenticated,
            "loginid": self.adapter.account_id,
            "account_type": self.adapter.account_type or self.adapter.account_mode,
            "currency": None,
            "scopes": self.oauth_scopes or [os.getenv("DERIV_OAUTH_SCOPE", "trade")],
            "live_execution_enabled": bool(self.adapter.live_trading_enabled) if authenticated else False,
            "expires_at": self.oauth_expires_at,
        }

    def oauth_status(self) -> dict[str, Any]:
        authenticated = bool(self.adapter.oauth_authenticated and self.adapter.account_id)
        return {
            "connected": authenticated,
            "loginid": self.adapter.account_id,
            "account_type": self.adapter.account_type or self.adapter.account_mode,
            "currency": None,
            "scopes": self.oauth_scopes or [os.getenv("DERIV_OAUTH_SCOPE", "trade")],
            "live_execution_enabled": bool(self.adapter.live_trading_enabled) if authenticated else False,
            "expires_at": self.oauth_expires_at,
        }

    async def run(self) -> None:
        self.state.status = "CONNECTING"
        self.state.auth_error = None
        print(f"DERIV_API_CONTEXT mcp={self.adapter.mcp_url} rest={self.adapter.rest_base}", flush=True)
        print("DERIV_CONNECT market_data", flush=True)
        await self.adapter.connect_market_data()

        # A persisted DERIV_AUTH_TOKEN can restore the account session after
        # a Render restart. OAuth callback authentication remains process-local
        # unless a token is supplied through the service environment.
        should_auto_connect = bool(
            self.adapter.auth_token
            or self.adapter.auth_method == "pat"
            or self.adapter.oauth_authenticated
        )
        print(
            f"DERIV_AUTH_MODE method={self.adapter.auth_method} "
            f"auto_connect={should_auto_connect} bearer_only={self.adapter.auth_method == 'oauth'}",
            flush=True,
        )
        if should_auto_connect:
            try:
                if not self.adapter.auth_token:
                    raise DerivAdapterError("Authenticated account token is missing")
                await self.adapter.connect_account()
                self._sync_account_state()
                self.state.status = "LIVE_ACCOUNT_CONNECTED"
                self._start_balance_loop()
                print(
                    f"DERIV_CONNECT account_connected mode={self.adapter.account_mode} "
                    f"account_id={self.adapter.account_id} live_execution_enabled={self.adapter.live_trading_enabled}",
                    flush=True,
                )
            except Exception as exc:
                self.state.auth_error = f"{type(exc).__name__}: {exc}"
                self._sync_account_state()
                print(
                    f"DERIV_ACCOUNT_CONNECT_ERROR type={type(exc).__name__} error={exc}",
                    flush=True,
                )
                self.state.status = "LIVE_DATA"
        else:
            print("DERIV_CONNECT account waiting_for_oauth", flush=True)

        symbols = await self.adapter.active_symbols()
        print(f"DERIV_SYMBOLS received={len(symbols)}", flush=True)
        available = {
            str(x.get("underlying_symbol") or x.get("symbol"))
            for x in symbols
            if x.get("underlying_symbol") or x.get("symbol")
        }
        gold_candidates = []
        for item in symbols:
            code = str(item.get("underlying_symbol") or item.get("symbol") or "")
            name = str(item.get("underlying_symbol_name") or item.get("display_name") or "").upper()
            if code and ("XAU" in code.upper() or "GOLD" in name or "XAU" in name):
                gold_candidates.append(code)

        candidates = []
        for candidate in [self.symbol, "frxXAUUSD", *gold_candidates]:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        selected = None
        for candidate in candidates:
            if candidate not in available:
                continue
            try:
                contracts = await self.adapter.contracts_for(candidate)
                if any(str(x.get("contract_type", "")).upper() in {"CALL", "PUT"} for x in contracts):
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
        if self.state.status == "CONNECTING":
            self.state.status = "LIVE_DATA"
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
                self.state.candle_data[tf] = [asdict(c) for c in self.candles[tf]]
                self.state.candles[tf] += 1
                signal = self.strategies[tf].generate(
                    self.symbol, self.candles[tf], self.stakes[tf]
                )
                if signal:
                    self.state.signals[tf] += 1
                    self.state.last_signals[tf] = {
                        "direction": signal.direction,
                        "stake": str(signal.stake),
                        "confidence": str(signal.confidence),
                        "expiry_seconds": signal.expiry_seconds,
                        "candle_timestamp": signal.candle_timestamp,
                        "reason": signal.reason,
                        "analysis": signal.analysis or {},
                    }
                    self.analytics.track(
                        "deriv_option_signal",
                        event_properties={
                            "symbol": signal.symbol,
                            "direction": signal.direction,
                            "timeframe_minutes": signal.timeframe_minutes,
                            "expiry_seconds": signal.expiry_seconds,
                            "stake": float(signal.stake),
                            "confidence": float(signal.confidence),
                            "reason": signal.reason,
                        },
                    )
                    await self._execute_signal(signal)
            self.state.updated_at = time.time()

    async def close(self) -> None:
        if self.balance_task is not None:
            self.balance_task.cancel()
            try:
                await self.balance_task
            except asyncio.CancelledError:
                pass
            self.balance_task = None
        await self.analytics.close()
        await self.adapter.close()


async def main() -> None:
    monitor = LiveMonitor()
    dashboard_server = await serve_dashboard(
        monitor.state,
        monitor.oauth_login_url,
        monitor.oauth_callback,
        monitor.oauth_status,
    )
    print(
        f"DASHBOARD_LISTENING host={os.getenv('DASHBOARD_HOST', '0.0.0.0')} "
        f"port={os.getenv('PORT', '10000')}",
        flush=True,
    )
    retry_delay = 5.0
    try:
        while True:
            try:
                await monitor.run()
                retry_delay = 5.0
            except Exception as exc:
                monitor.state.status = "DATA_ERROR"
                monitor.state.updated_at = time.time()
                monitor.state.last_signals[0] = {"error": str(exc)}
                print(
                    f"DERIV_MONITOR_ERROR type={type(exc).__name__} error={exc} "
                    f"retry_in={retry_delay:.1f}s",
                    flush=True,
                )
                await monitor.close()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 120.0)
    finally:
        dashboard_server.close()
        await dashboard_server.wait_closed()
        await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
