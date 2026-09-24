from __future__ import annotations

"""Isolated Base gas scanner for Dragon.

The gas path owns its own RPC pool and mutable health state. It does not share
the DEX adapter, DEX RpcPool, quote cache, cooldowns, or locks.
"""

import logging
import os
import re
import time
from decimal import Decimal
from threading import Lock
from web3 import Web3

from src.dragon.rpc_providers import load_providers, private_urls

BASE_CHAIN_ID = 8453
DEFAULT_PUBLIC_GAS_RPCS = ("https://base-rpc.publicnode.com", "https://mainnet.base.org")


def _env_list(*names: str) -> list[str]:
    out: list[str] = []
    for name in names:
        for value in re.split(r"[;,\n]+", os.getenv(name, "").strip()):
            value = value.strip()
            if value and value not in out:
                out.append(value)
    return out


class GasRpcPool:
    """Dedicated, bounded, failover RPC pool for gas only."""

    def __init__(self, urls: list[str] | None = None, timeout: float | None = None):
        configured = urls or _env_list("DEX_GAS_RPC_URLS", "DEX_GAS_RPC_URL")
        if not configured:
            configured = private_urls(BASE_CHAIN_ID, load_providers())
        for url in DEFAULT_PUBLIC_GAS_RPCS:
            if url not in configured:
                configured.append(url)
        if not configured:
            raise RuntimeError("gas scanner has no Base RPC endpoints")

        self.urls = configured
        self.timeout = max(0.2, min(2.0, float(timeout or os.getenv("DEX_GAS_RPC_TIMEOUT_SECONDS", "0.4"))))
        self.max_attempts = max(1, min(len(self.urls), int(os.getenv("DEX_GAS_RPC_MAX_ATTEMPTS", "4"))))
        self.max_inflight = max(1, int(os.getenv("DEX_GAS_RPC_MAX_INFLIGHT", "2")))
        self.cooldown_seconds = max(0.5, float(os.getenv("DEX_GAS_RPC_COOLDOWN_SECONDS", "3")))
        self._lock = Lock()
        self._cooldown_until = [0.0] * len(self.urls)
        self._success = [0] * len(self.urls)
        self._errors = [0] * len(self.urls)
        self._latency_ms = [0.0] * len(self.urls)
        self._inflight = [0] * len(self.urls)
        self._active = 0
        self._index = 0
        self._clients: dict[str, Web3] = {}
        self._last_endpoint = ""
        self._last_error: str | None = None

    @staticmethod
    def _host(url: str) -> str:
        return url.split("//", 1)[-1].split("/", 1)[0] or url

    def _client(self, idx: int) -> Web3:
        url = self.urls[idx]
        client = self._clients.get(url)
        if client is None:
            client = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": self.timeout}))
            self._clients[url] = client
        return client

    def _eligible(self, now: float, attempted: set[int]) -> list[int]:
        with self._lock:
            return [
                i for i in range(len(self.urls))
                if i not in attempted and self._cooldown_until[i] <= now
                and self._inflight[i] < self.max_inflight
            ]

    def call(self, fn, *, deadline: float | None = None):
        attempted: set[int] = set()
        last_exc: Exception | None = None
        for _ in range(self.max_attempts):
            ready = self._eligible(time.monotonic(), attempted)
            if not ready:
                break
            with self._lock:
                idx = min(ready, key=lambda i: (
                    self._inflight[i], self._errors[i], self._latency_ms[i] or 0.0,
                    (i - self._index) % len(self.urls),
                ))
                self._inflight[idx] += 1
                self._active += 1
                self._index = (idx + 1) % len(self.urls)
            attempted.add(idx)
            started = time.monotonic()
            try:
                if deadline is not None and time.monotonic() + self.timeout > deadline:
                    raise TimeoutError("gas RPC deadline exhausted")
                client = self._client(idx)
                if int(client.eth.chain_id) != BASE_CHAIN_ID:
                    raise RuntimeError("gas RPC returned wrong chain")
                result = fn(client)
                elapsed = (time.monotonic() - started) * 1000.0
                with self._lock:
                    self._success[idx] += 1
                    self._latency_ms[idx] = elapsed if not self._latency_ms[idx] else 0.8 * self._latency_ms[idx] + 0.2 * elapsed
                    self._last_endpoint = self._host(self.urls[idx])
                    self._last_error = None
                return result, elapsed, idx
            except Exception as exc:
                last_exc = exc
                with self._lock:
                    self._errors[idx] += 1
                    self._cooldown_until[idx] = time.monotonic() + self.cooldown_seconds
                    self._last_error = f"{type(exc).__name__}: {exc}"
                logging.warning("gas RPC failure endpoint=%s cooldown=%.1fs error=%s", self._host(self.urls[idx]), self.cooldown_seconds, exc)
            finally:
                with self._lock:
                    self._inflight[idx] = max(0, self._inflight[idx] - 1)
                    self._active = max(0, self._active - 1)
        raise RuntimeError(f"gas RPC failover exhausted: {last_exc}")

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "active_endpoint": self._last_endpoint,
                "active_calls": self._active,
                "max_inflight": self.max_inflight,
                "timeout_seconds": self.timeout,
                "last_error": self._last_error,
                "endpoints": [
                    {
                        "host": self._host(url),
                        "success": self._success[i],
                        "errors": self._errors[i],
                        "latency_ms": round(self._latency_ms[i], 2),
                        "inflight": self._inflight[i],
                        "cooling_down": self._cooldown_until[i] > now,
                    }
                    for i, url in enumerate(self.urls)
                ],
            }


class GasScanner:
    def __init__(self, rpc_url: str | None = None, timeout: float | None = None):
        # This pool is independent of the DEX scanner's RpcPool.
        self.rpc_pool = GasRpcPool(urls=[rpc_url] if rpc_url else None, timeout=timeout)
        self.last_scan: dict = {}
        self.scans = 0
        self.failures = 0

    @staticmethod
    def _dec(value, default="0") -> Decimal:
        try:
            result = Decimal(str(value))
            return result if result.is_finite() else Decimal(default)
        except Exception:
            return Decimal(default)

    @staticmethod
    def _gas_units(execution) -> int:
        return max(0, int(getattr(execution, "gas", 0) or 0))

    def current_gas_price(self, *, deadline: float | None = None) -> tuple[int, float, int]:
        return self.rpc_pool.call(lambda w3: int(w3.eth.gas_price), deadline=deadline)

    def scan_opportunity(self, opportunity, *, min_profit: Decimal) -> dict:
        self.scans += 1
        deadline = time.monotonic() + self.rpc_pool.timeout
        try:
            gas_price_wei, latency_ms, endpoint_idx = self.current_gas_price(deadline=deadline)
            first = getattr(opportunity, "first_leg", None)
            second = getattr(opportunity, "second_leg", None)
            gas_units = self._gas_units(first) + self._gas_units(second)
            if gas_units <= 0:
                raise RuntimeError("gas scanner received zero gas estimate")

            overhead = max(Decimal("1"), self._dec(os.getenv("DEX_GAS_EXECUTION_OVERHEAD", "1.10"), "1"))
            adjusted_gas_units = int(Decimal(gas_units) * overhead)
            gas_native = Decimal(adjusted_gas_units) * Decimal(gas_price_wei) / Decimal(10**18)

            native_to_quote = self._dec(os.getenv("DEX_NATIVE_TO_QUOTE_RATE", "0"))
            existing_gas_quote = self._dec(getattr(opportunity, "gas_cost_quote", 0))
            existing_gas_native = (
                Decimal(self._gas_units(first)) * self._dec(getattr(first, "gas_price", 0)) / Decimal(10**18)
                + Decimal(self._gas_units(second)) * self._dec(getattr(second, "gas_price", 0)) / Decimal(10**18)
            )
            if native_to_quote <= 0 and existing_gas_native > 0 and existing_gas_quote > 0:
                native_to_quote = existing_gas_quote / existing_gas_native
            if native_to_quote <= 0:
                raise RuntimeError("gas scanner has no native-to-quote conversion")

            gas_cost_quote = gas_native * native_to_quote
            gross = self._dec(getattr(opportunity, "gross_profit_quote", 0))
            flash = self._dec(getattr(opportunity, "flash_loan_fee_quote", 0))
            safety = self._dec(getattr(opportunity, "safety_buffer_quote", 0))
            existing_net = self._dec(getattr(opportunity, "net_profit_quote", 0))
            other_costs = max(Decimal("0"), gross - existing_net - existing_gas_quote - flash - safety)
            minimum = Decimal(str(min_profit))
            gas_ceiling = max(Decimal("0"), gross - other_costs - flash - safety - minimum)
            gas_adjusted_net = gross - other_costs - flash - safety - gas_cost_quote
            passed = gas_cost_quote <= gas_ceiling and gas_adjusted_net >= minimum

            result = {
                "chain_id": BASE_CHAIN_ID,
                "endpoint": self.rpc_pool._host(self.rpc_pool.urls[endpoint_idx]),
                "rpc_latency_ms": round(latency_ms, 2),
                "gas_price_wei": str(gas_price_wei),
                "gas_price_gwei": str(Decimal(gas_price_wei) / Decimal(10**9)),
                "gas_estimate": gas_units,
                "execution_overhead_multiplier": str(overhead),
                "adjusted_gas_estimate": adjusted_gas_units,
                "gas_cost_native": str(gas_native),
                "native_to_quote_rate": str(native_to_quote),
                "estimated_gas_cost_quote": str(gas_cost_quote),
                "gas_ceiling_quote": str(gas_ceiling),
                "gas_adjusted_net_profit_quote": str(gas_adjusted_net),
                "passed": passed,
                "timestamp": time.time(),
                "rpc": self.rpc_pool.status(),
            }
            self.last_scan = result
            return result
        except Exception:
            self.failures += 1
            raise

    def status(self) -> dict:
        return {
            "enabled": True,
            "chain_id": BASE_CHAIN_ID,
            "scans": self.scans,
            "failures": self.failures,
            "last_scan": self.last_scan,
            "rpc": self.rpc_pool.status(),
        }
