"""Deriv live-market-data + demo-execution adapter.

Market data uses Deriv's unauthenticated Options WebSocket. Account authentication
uses the authenticated Options WebSocket URL returned by the OTP REST endpoint.
Real-account authentication is permitted read-only; order execution remains explicitly gated.
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

from options_engine.execution import ExecutionAdapter


REST_BASE = "https://api.derivws.com"
PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"
DEMO_WS_MARKER = "/trading/v1/options/ws/demo"
REAL_WS_MARKER = "/trading/v1/options/ws/real"
FIXED_STAKES = {60: Decimal("0.5"), 300: Decimal("2")}


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
class DerivDemoContract:
    contract_id: str
    buy_price: Decimal
    raw: dict[str, Any]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise DerivAdapterError(f"invalid numeric field: {field}") from exc


class DerivOptionsDemo(ExecutionAdapter):
    """Read live Deriv ticks and authenticate against demo or real accounts.

    Real-account order execution remains explicitly gated by
    DERIV_LIVE_TRADING_ENABLED and the engine live-mode lock.
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
        self.auth_token = auth_token or os.getenv("DERIV_AUTH_TOKEN")
        self.app_id = app_id or os.getenv("DERIV_APP_ID")
        self.account_id = account_id or os.getenv("DERIV_ACCOUNT_ID")
        self.account_mode = (account_mode or os.getenv("DERIV_ACCOUNT_MODE", "demo")).lower()
        enabled_env = os.getenv("DERIV_LIVE_TRADING_ENABLED", "false").lower() == "true"
        self.live_trading_enabled = enabled_env if live_trading_enabled is None else live_trading_enabled
        if self.account_mode not in {"demo", "real"}:
            raise ValueError("DERIV_ACCOUNT_MODE must be demo or real")
        # Real-account authentication is allowed for read-only verification.
        # Actual trading remains gated inside submit().
        self.rest_base = rest_base.rstrip("/")
        self.public_ws = public_ws
        self.timeout = timeout
        self._market_ws = None
        self._demo_ws = None
        self._req_id = 0
        self.connected = False
        self.enabled = True

    def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _require_credentials(self) -> None:
        missing = []
        if not self.auth_token:
            missing.append("DERIV_AUTH_TOKEN")
        if not self.account_id:
            missing.append("DERIV_ACCOUNT_ID")
        if missing:
            raise DerivAdapterError(
                f"Missing Deriv credentials for {self.account_mode} account: {', '.join(missing)}"
            )

    @staticmethod
    def _assert_demo_url(url: str) -> None:
        if DEMO_WS_MARKER not in url or "/real" in url:
            raise DerivLiveExecutionBlocked(
                "Only Deriv's demo Options WebSocket is permitted by this adapter"
            )

    def _assert_account_url(self, url: str) -> None:
        expected = REAL_WS_MARKER if self.account_mode == "real" else DEMO_WS_MARKER
        forbidden = DEMO_WS_MARKER if self.account_mode == "real" else REAL_WS_MARKER
        if expected not in url or forbidden in url:
            raise DerivLiveExecutionBlocked(
                f"Deriv {self.account_mode} account URL validation failed"
            )

    async def _request_account_ws_url(self) -> str:
        self._require_credentials()
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        if self.app_id:
            headers["Deriv-App-ID"] = self.app_id
        url = f"{self.rest_base}/trading/v1/options/accounts/{self.account_id}/otp"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        ws_url = payload.get("data", {}).get("url")
        if not isinstance(ws_url, str) or not ws_url:
            raise DerivAdapterError("Deriv OTP response did not contain data.url")
        self._assert_account_url(ws_url)
        return ws_url

    async def connect(self) -> None:
        await self.connect_market_data()
        await self.connect_account()

    async def connect_account(self) -> None:
        ws_url = await self._request_account_ws_url()
        if self._demo_ws is not None:
            await self._demo_ws.close()
        self._demo_ws = await websockets.connect(
            ws_url, ping_interval=20, ping_timeout=20
        )
        self.connected = True

    async def connect_market_data(self) -> None:
        if self._market_ws is None:
            self._market_ws = await websockets.connect(
                self.public_ws, ping_interval=20, ping_timeout=20
            )

    async def connect_demo(self) -> None:
        if self.account_mode != "demo":
            raise DerivLiveExecutionBlocked("connect_demo requires DERIV_ACCOUNT_MODE=demo")
        ws_url = await self._request_demo_ws_url()
        if self._demo_ws is not None:
            await self._demo_ws.close()
        self._demo_ws = await websockets.connect(
            ws_url, ping_interval=20, ping_timeout=20
        )
        self.connected = True

    async def close(self) -> None:
        for ws in (self._market_ws, self._demo_ws):
            if ws is not None:
                await ws.close()
        self._market_ws = None
        self._demo_ws = None
        self.connected = False

    async def _send(self, ws: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if ws is None:
            raise DerivAdapterError("WebSocket is not connected")
        await ws.send(json.dumps(payload))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
            message = json.loads(raw)
            if message.get("error"):
                error = message["error"]
                raise DerivAdapterError(
                    f"Deriv API error {error.get('code')}: {error.get('message')}"
                )
            if message.get("req_id") == payload.get("req_id"):
                return message

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
        if self._demo_ws is None:
            raise DerivAdapterError("account WebSocket is not connected")
        direction = direction.upper()
        if direction not in {"CALL", "PUT"}:
            raise ValueError("direction must be CALL or PUT")
        if stake <= 0:
            raise ValueError("stake must be positive")
        if duration_seconds not in FIXED_STAKES:
            raise ValueError("duration_seconds must be 60 or 300")
        expected_stake = FIXED_STAKES[duration_seconds]
        if stake != expected_stake:
            raise ValueError(
                f"fixed stake violation: {duration_seconds}s requires {expected_stake}, got {stake}"
            )
        req_id = self._next_req_id()
        response = await self._send(
            self._demo_ws,
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

    async def buy(self, proposal_id: str, price: Decimal) -> DerivDemoContract:
        if self._demo_ws is None:
            raise DerivAdapterError("demo WebSocket is not connected")
        if not proposal_id:
            raise ValueError("proposal_id is required")
        if price <= 0:
            raise ValueError("price must be positive")
        req_id = self._next_req_id()
        response = await self._send(
            self._demo_ws,
            {"buy": proposal_id, "price": float(price), "req_id": req_id},
        )
        buy = response.get("buy") or {}
        contract_id = buy.get("contract_id")
        if contract_id is None:
            raise DerivAdapterError("Deriv buy response did not contain contract_id")
        return DerivDemoContract(
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
                "Real Deriv execution is locked: set DERIV_LIVE_TRADING_ENABLED=true explicitly"
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
        }

    async def contract_status(self, contract_id: str) -> dict[str, Any]:
        if self._demo_ws is None:
            raise DerivAdapterError("demo WebSocket is not connected")
        req_id = self._next_req_id()
        response = await self._send(
            self._demo_ws,
            {
                "proposal_open_contract": 1,
                "contract_id": int(contract_id),
                "subscribe": 1,
                "req_id": req_id,
            },
        )
        return response.get("proposal_open_contract", {})

    async def balance(self) -> Decimal:
        if self._demo_ws is None:
            raise DerivAdapterError("demo WebSocket is not connected")
        req_id = self._next_req_id()
        response = await self._send(self._demo_ws, {"balance": 1, "req_id": req_id})
        return _decimal(response.get("balance", {}).get("balance"), "balance.balance")
