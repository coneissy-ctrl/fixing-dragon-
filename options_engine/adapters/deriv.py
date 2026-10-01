"""Deriv Options adapter using the current New API REST + authenticated WebSocket flow.

Deriv's MCP endpoint is an AI/developer discovery surface. Runtime trading remains on
Deriv's documented REST and WebSocket APIs. The MCP URL is kept as configuration so
the engine records which Deriv API context it was built against without making live
trading dependent on an AI tool server.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, AsyncIterator

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from options_engine.execution import ExecutionAdapter


REST_BASE = "https://api.derivws.com"
PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"
DEMO_WS_MARKER = "/trading/v1/options/ws/demo"
REAL_WS_MARKER = "/trading/v1/options/ws/real"
DERIV_MCP_URL = "https://mcp-api.deriv.com/mcp"
FIXED_STAKES = {30: Decimal("0.5"), 60: Decimal("0.5"), 300: Decimal("2")}
DEFAULT_MAX_STAKES = {60: Decimal(os.getenv("DERIV_MAX_STAKE_1M", "5")), 300: Decimal(os.getenv("DERIV_MAX_STAKE_5M", "10"))}


class DerivAdapterError(RuntimeError):
    pass


class DerivLiveExecutionBlocked(DerivAdapterError):
    pass


@dataclass(frozen=True)
class DerivTick:
    symbol: str
    quote: Decimal
    epoch: int


@dataclass(frozen=True)
class DerivProposal:
    proposal_id: str
    ask_price: Decimal
    payout: Decimal | None
    spot: Decimal | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class DerivContract:
    contract_id: str
    buy_price: Decimal
    raw: dict[str, Any]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise DerivAdapterError(f"invalid numeric field: {field}") from exc


def _api_error(response: httpx.Response, operation: str) -> DerivAdapterError:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        code = first.get("code", "Unknown")
        message = first.get("message", response.text[:300])
        return DerivAdapterError(
            f"Deriv {operation} HTTP {response.status_code} {code}: {message}"
        )
    return DerivAdapterError(
        f"Deriv {operation} HTTP {response.status_code}: {response.text[:300]}"
    )


class DerivOptionsDemo(ExecutionAdapter):
    """Deriv Options runtime adapter for demo or real account channels.

    Public market data never requires OAuth. Account-scoped operations require an
    OAuth/PAT token and the REST OTP flow. Real order submission is still explicitly
    gated by DERIV_LIVE_TRADING_ENABLED.
    """

    def __init__(
        self,
        *,
        auth_token: str | None = None,
        app_id: str | None = None,
        account_id: str | None = None,
        account_mode: str | None = None,
        live_trading_enabled: bool | None = None,
        rest_base: str = REST_BASE,
        public_ws: str = PUBLIC_WS,
        timeout: float = 10.0,
    ):
        self.auth_method = os.getenv("DERIV_AUTH_METHOD", "oauth").lower()
        # OAuth/PAT bearer tokens may be supplied by Render environment variables.
        # This lets a configured token survive a Render process restart.
        self.auth_token = auth_token if auth_token is not None else (os.getenv("DERIV_PAT") or os.getenv("DERIV_AUTH_TOKEN"))
        self.app_id = app_id or os.getenv("DERIV_APP_ID")
        if self.auth_method not in {"oauth", "pat"}:
            raise ValueError("DERIV_AUTH_METHOD must be oauth or pat")
        self.account_id = account_id or os.getenv("DERIV_ACCOUNT_ID")
        self.account_mode = (account_mode or os.getenv("DERIV_ACCOUNT_MODE", "demo")).lower()
        if self.account_mode not in {"demo", "real"}:
            raise ValueError("DERIV_ACCOUNT_MODE must be demo or real")
        enabled_env = os.getenv("DERIV_LIVE_TRADING_ENABLED", "false").lower() == "true"
        self.live_trading_enabled = (
            enabled_env if live_trading_enabled is None else live_trading_enabled
        )
        self.mcp_url = os.getenv("DERIV_MCP_URL", DERIV_MCP_URL)
        self.rest_base = rest_base.rstrip("/")
        self.public_ws = public_ws
        self.timeout = timeout
        self._market_ws: Any | None = None
        self._account_ws: Any | None = None
        self._account_ws_lock = asyncio.Lock()
        self._req_id = 0
        self.connected = False
        self.enabled = True
        self.account_type: str | None = None
        self.oauth_authenticated = False

    def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _require_credentials(self) -> None:
        missing = []
        if not self.auth_token:
            missing.append("DERIV_PAT (or DERIV_AUTH_TOKEN)")
        if not self.account_id:
            missing.append("DERIV_ACCOUNT_ID")
        if missing:
            raise DerivAdapterError(
                f"Missing Deriv credentials for {self.account_mode} account: {', '.join(missing)}"
            )

    def _auth_headers(self) -> dict[str, str]:
        self._require_credentials()
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/json",
        }
        if self.auth_method == "pat":
            if not self.app_id:
                raise DerivAdapterError("DERIV_APP_ID is required when DERIV_AUTH_METHOD=pat")
            headers["Deriv-App-ID"] = self.app_id
        return headers

    def _assert_account_url(self, url: str) -> None:
        expected = REAL_WS_MARKER if self.account_mode == "real" else DEMO_WS_MARKER
        forbidden = DEMO_WS_MARKER if self.account_mode == "real" else REAL_WS_MARKER
        if expected not in url or forbidden in url:
            raise DerivLiveExecutionBlocked(
                f"Deriv {self.account_mode} account WebSocket URL validation failed"
            )

    async def _request_account_ws_url(self) -> str:
        headers = self._auth_headers()
        url = f"{self.rest_base}/trading/v1/options/accounts/{self.account_id}/otp"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers)
        if response.is_error:
            raise _api_error(response, "OTP")
        payload = response.json()
        data = payload.get("data", {})
        ws_url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(ws_url, str) or not ws_url:
            raise DerivAdapterError("Deriv OTP response did not contain data.url")
        self._assert_account_url(ws_url)
        return ws_url

    async def set_oauth_token(self, access_token: str) -> None:
        if not access_token:
            raise DerivAdapterError("OAuth access token is empty")
        self.auth_token = access_token
        self.account_id = None
        self.oauth_authenticated = True
        await self.discover_account_id()

    async def discover_account_id(self) -> str:
        if not self.auth_token:
            raise DerivAdapterError("OAuth/PAT token is required for account discovery")
        headers = self._auth_headers() if self.account_id else {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/json",
            **({"Deriv-App-ID": self.app_id} if self.auth_method == "pat" and self.app_id else {}),
        }
        if self.auth_method == "pat" and not self.app_id:
            raise DerivAdapterError("DERIV_APP_ID is required when DERIV_AUTH_METHOD=pat")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.rest_base}/trading/v1/options/accounts",
                headers=headers,
            )
        if response.is_error:
            raise _api_error(response, "account discovery")
        payload = response.json()
        accounts = payload.get("data", [])
        if isinstance(accounts, dict):
            accounts = accounts.get("accounts") or accounts.get("data") or []
        if not isinstance(accounts, list):
            raise DerivAdapterError("Deriv accounts response has an unexpected shape")

        preferred = [
            a for a in accounts
            if isinstance(a, dict)
            and str(a.get("account_type", "")).lower() == self.account_mode
        ]
        ordered = preferred + [a for a in accounts if a not in preferred]
        for account in ordered:
            if not isinstance(account, dict):
                continue
            account_id = account.get("account_id") or account.get("id")
            if not account_id:
                continue
            account_type = str(account.get("account_type", "")).lower()
            if account_type and account_type != self.account_mode:
                continue
            self.account_id = str(account_id)
            self.account_type = account_type or self.account_mode
            return self.account_id

        raise DerivAdapterError(
            f"No {self.account_mode} Deriv Options account was returned"
        )

    async def connect_market_data(self) -> None:
        if self._market_ws is None:
            self._market_ws = await websockets.connect(
                self.public_ws, ping_interval=20, ping_timeout=20
            )

    async def connect_account(self) -> None:
        if not self.auth_token:
            raise DerivAdapterError("Deriv authentication is not established")
        async with self._account_ws_lock:
            if not self.account_id:
                await self.discover_account_id()
            ws_url = await self._request_account_ws_url()
            old_ws = self._account_ws
            self._account_ws = None
            self.connected = False
            if old_ws is not None:
                try:
                    await old_ws.close()
                except Exception:
                    pass
            self._account_ws = await websockets.connect(
                ws_url,
                ping_interval=15,
                ping_timeout=15,
                close_timeout=5,
                max_queue=64,
            )
            self.connected = True

    async def connect(self) -> None:
        await self.connect_market_data()
        await self.connect_account()

    async def close(self) -> None:
        for ws in (self._market_ws, self._account_ws):
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass
        self._market_ws = None
        self._account_ws = None
        self.connected = False

    async def _send(
        self,
        ws: Any,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if ws is None:
            raise DerivAdapterError("Deriv WebSocket is not connected")
        try:
            await ws.send(json.dumps(payload))
            deadline = timeout or self.timeout
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline)
                message = json.loads(raw)
                if message.get("error"):
                    error = message["error"]
                    raise DerivAdapterError(
                        f"Deriv API error {error.get('code')}: {error.get('message')}"
                    )
                if message.get("req_id") == payload.get("req_id"):
                    return message
        except ConnectionClosed as exc:
            if ws is self._account_ws:
                self._account_ws = None
                self.connected = False
            raise DerivAdapterError(
                f"Deriv account WebSocket closed code={exc.code} reason={exc.reason or 'none'}"
            ) from exc

    async def active_symbols(self) -> list[dict[str, Any]]:
        req_id = self._next_req_id()
        response = await self._send(
            self._market_ws,
            {"active_symbols": "brief", "contract_type": ["CALL", "PUT"], "req_id": req_id},
        )
        return response.get("active_symbols", [])

    async def contracts_for(self, symbol: str) -> list[dict[str, Any]]:
        req_id = self._next_req_id()
        response = await self._send(
            self._market_ws, {"contracts_for": symbol, "req_id": req_id}
        )
        return response.get("contracts_for", {}).get("available", [])

    async def subscribe_ticks(self, symbol: str) -> None:
        req_id = self._next_req_id()
        await self._send(
            self._market_ws, {"ticks": symbol, "subscribe": 1, "req_id": req_id}
        )

    async def ticks(self, symbol: str) -> AsyncIterator[DerivTick]:
        if self._market_ws is None:
            raise DerivAdapterError("market-data WebSocket is not connected")
        await self.subscribe_ticks(symbol)
        while True:
            raw = await asyncio.wait_for(self._market_ws.recv(), timeout=self.timeout)
            message = json.loads(raw)
            if message.get("error"):
                error = message["error"]
                raise DerivAdapterError(
                    f"Deriv tick error {error.get('code')}: {error.get('message')}"
                )
            if message.get("msg_type") != "tick":
                continue
            tick = message.get("tick", {})
            yield DerivTick(
                symbol=str(tick.get("symbol", symbol)),
                quote=_decimal(tick.get("quote"), "tick.quote"),
                epoch=int(tick["epoch"]),
            )

    async def proposal(
        self,
        *,
        symbol: str,
        direction: str,
        stake: Decimal,
        duration_seconds: int,
        currency: str = "USD",
    ) -> DerivProposal:
        if self._account_ws is None:
            raise DerivAdapterError("authenticated Deriv WebSocket is not connected")
        direction = direction.upper()
        if direction not in {"CALL", "PUT"}:
            raise ValueError("direction must be CALL or PUT")
        if stake <= 0:
            raise ValueError("stake must be positive")
        if duration_seconds not in FIXED_STAKES:
            raise ValueError("duration_seconds must be 30, 60 or 300")
        minimum_stake = FIXED_STAKES[duration_seconds]
        maximum_stake = DEFAULT_MAX_STAKES[duration_seconds]
        if stake < minimum_stake:
            raise ValueError(
                f"stake below configured minimum: {duration_seconds}s requires at least {minimum_stake}, got {stake}"
            )
        if stake > maximum_stake:
            raise ValueError(
                f"stake above configured maximum: {duration_seconds}s allows at most {maximum_stake}, got {stake}"
            )
        req_id = self._next_req_id()
        response = await self._send(
            self._account_ws,
            {
                "proposal": 1,
                "amount": float(stake),
                "basis": "stake",
                "contract_type": direction,
                "currency": currency,
                "duration": duration_seconds,
                "duration_unit": "s",
                "underlying_symbol": symbol,
                "req_id": req_id,
            },
        )
        proposal = response.get("proposal") or {}
        proposal_id = proposal.get("id")
        if not proposal_id:
            raise DerivAdapterError("Deriv proposal response did not contain proposal.id")
        return DerivProposal(
            proposal_id=str(proposal_id),
            ask_price=_decimal(proposal.get("ask_price"), "proposal.ask_price"),
            payout=(
                _decimal(proposal["payout"], "proposal.payout")
                if proposal.get("payout") is not None
                else None
            ),
            spot=(
                _decimal(proposal["spot"], "proposal.spot")
                if proposal.get("spot") is not None
                else None
            ),
            raw=proposal,
        )

    async def buy(self, proposal_id: str, price: Decimal) -> DerivContract:
        if self._account_ws is None:
            raise DerivAdapterError("authenticated Deriv WebSocket is not connected")
        if not proposal_id:
            raise ValueError("proposal_id is required")
        if price <= 0:
            raise ValueError("price must be positive")
        req_id = self._next_req_id()
        response = await self._send(
            self._account_ws,
            {"buy": proposal_id, "price": float(price), "req_id": req_id},
        )
        buy = response.get("buy") or {}
        contract_id = buy.get("contract_id")
        if contract_id is None:
            raise DerivAdapterError("Deriv buy response did not contain contract_id")
        return DerivContract(
            contract_id=str(contract_id),
            buy_price=_decimal(buy.get("buy_price", price), "buy.buy_price"),
            raw=buy,
        )

    async def submit(
        self,
        symbol: str,
        direction: str,
        stake: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.account_mode == "real" and not self.live_trading_enabled:
            raise DerivLiveExecutionBlocked(
                "Real Deriv execution is locked: DERIV_LIVE_TRADING_ENABLED=true is required"
            )
        duration_seconds = int(kwargs.get("duration_seconds", 60))
        proposal = await self.proposal(
            symbol=symbol,
            direction=direction,
            stake=stake,
            duration_seconds=duration_seconds,
            currency=str(kwargs.get("currency", "USD")),
        )
        contract = await self.buy(proposal.proposal_id, proposal.ask_price)
        return {
            "id": contract.contract_id,
            "contract_id": contract.contract_id,
            "symbol": symbol,
            "direction": direction.upper(),
            "stake": str(stake),
            "buy_price": str(contract.buy_price),
            "duration_seconds": duration_seconds,
            "status": "OPEN",
            "paper": False,
            "demo": self.account_mode == "demo",
            "real": self.account_mode == "real",
            "deriv_mcp_url": self.mcp_url,
        }

    async def contract_status(self, contract_id: str) -> dict[str, Any]:
        if self._account_ws is None:
            raise DerivAdapterError("authenticated Deriv WebSocket is not connected")
        req_id = self._next_req_id()
        response = await self._send(
            self._account_ws,
            {
                "proposal_open_contract": 1,
                "contract_id": int(contract_id),
                "subscribe": 1,
                "req_id": req_id,
            },
        )
        return response.get("proposal_open_contract", {})

    async def balance(self) -> Decimal:
        # Deriv can close an authenticated account socket while the public feed
        # remains healthy. Always obtain a fresh OTP and reconnect before retrying.
        # Keep the request one-shot here; the monitor polls every few seconds.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if self._account_ws is None or not self.connected:
                    await self.connect_account()
                req_id = self._next_req_id()
                response = await self._send(
                    self._account_ws,
                    {"balance": 1, "req_id": req_id},
                    timeout=self.timeout,
                )
                balance_payload = response.get("balance") or {}
                value = balance_payload.get("balance")
                if value is None:
                    raise DerivAdapterError("Deriv balance response did not contain balance.balance")
                return _decimal(value, "balance.balance")
            except (DerivAdapterError, ConnectionClosed) as exc:
                last_error = exc
                self.connected = False
                if self._account_ws is not None:
                    try:
                        await self._account_ws.close()
                    except Exception:
                        pass
                    self._account_ws = None
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                break
        raise DerivAdapterError(f"Deriv balance unavailable after reconnect: {last_error}")
