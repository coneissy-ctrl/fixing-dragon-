from __future__ import annotations

"""Isolated Base gas scanner for Dragon.

This module has no dependency on the DEX opportunity scanner. It reads the
current Base gas price through its own RPC connection and evaluates the gas
budget independently before an opportunity can pass execution economics.
"""

import os
import time
from decimal import Decimal
from web3 import Web3


BASE_CHAIN_ID = 8453


class GasScanner:
    def __init__(self, rpc_url: str | None = None, timeout: float | None = None):
        self.rpc_url = (
            rpc_url
            or os.getenv("DEX_GAS_RPC_URL")
            or os.getenv("BASE_RPC_URL")
            or os.getenv("DEX_RPC_URL")
            or "https://base-rpc.publicnode.com"
        )
        self.timeout = float(timeout or os.getenv("DEX_GAS_RPC_TIMEOUT_SECONDS", "0.4"))
        self.w3 = Web3(
            Web3.HTTPProvider(
                self.rpc_url,
                request_kwargs={"timeout": self.timeout},
            )
        )
        self.last_scan: dict = {}

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

    def current_gas_price(self) -> tuple[int, float]:
        started = time.perf_counter()
        chain_id = int(self.w3.eth.chain_id)
        if chain_id != BASE_CHAIN_ID:
            raise RuntimeError(f"gas scanner wrong chain: expected {BASE_CHAIN_ID}, got {chain_id}")
        price = int(self.w3.eth.gas_price)
        return price, (time.perf_counter() - started) * 1000

    def scan_opportunity(self, opportunity, *, min_profit: Decimal) -> dict:
        """Independently recompute gas economics for one two-leg opportunity."""
        gas_price_wei, latency_ms = self.current_gas_price()
        gas_units = self._gas_units(opportunity.first_leg) + self._gas_units(opportunity.second_leg)

        configured_overhead = self._dec(os.getenv("DEX_GAS_EXECUTION_OVERHEAD", "1.10"), "1")
        if configured_overhead < 1:
            configured_overhead = Decimal("1")
        gas_units_adjusted = int(Decimal(gas_units) * configured_overhead)

        gas_native = (
            Decimal(gas_units_adjusted) * Decimal(gas_price_wei) / Decimal(10**18)
        )

        # Prefer an explicit native->quote conversion. Otherwise infer the
        # conversion from the opportunity's independently calculated gas cost;
        # this keeps the gas scanner usable for stablecoin quote assets without
        # introducing a second price oracle into the critical path.
        native_to_quote = self._dec(os.getenv("DEX_NATIVE_TO_QUOTE_RATE", "0"))
        existing_gas_quote = self._dec(getattr(opportunity, "gas_cost_quote", 0))
        existing_gas_native = self._dec(
            (
                self._gas_units(opportunity.first_leg) * self._dec(getattr(opportunity.first_leg, "gas_price", 0))
                + self._gas_units(opportunity.second_leg) * self._dec(getattr(opportunity.second_leg, "gas_price", 0))
            )
            / Decimal(10**18)
        )
        if native_to_quote <= 0 and existing_gas_native > 0 and existing_gas_quote > 0:
            native_to_quote = existing_gas_quote / existing_gas_native

        if native_to_quote <= 0:
            raise RuntimeError("gas scanner has no native-to-quote conversion")

        gas_cost_quote = gas_native * native_to_quote

        gross = self._dec(getattr(opportunity, "gross_profit_quote", 0))
        flash = self._dec(getattr(opportunity, "flash_loan_fee_quote", 0))
        safety = self._dec(getattr(opportunity, "safety_buffer_quote", 0))
        # Costs already embedded in the opportunity other than gas/flash/safety.
        other_costs = max(
            Decimal("0"),
            gross
            - self._dec(getattr(opportunity, "net_profit_quote", 0))
            - existing_gas_quote
            - flash
            - safety,
        )
        gas_ceiling = max(
            Decimal("0"),
            gross - other_costs - flash - safety - Decimal(str(min_profit)),
        )
        gas_adjusted_net = gross - other_costs - flash - safety - gas_cost_quote
        passed = (
            gas_cost_quote <= gas_ceiling
            and gas_adjusted_net >= Decimal(str(min_profit))
        )

        result = {
            "chain_id": BASE_CHAIN_ID,
            "rpc_url": self.rpc_url,
            "rpc_latency_ms": round(latency_ms, 2),
            "gas_price_wei": str(gas_price_wei),
            "gas_price_gwei": str(Decimal(gas_price_wei) / Decimal(10**9)),
            "gas_estimate": gas_units,
            "execution_overhead_multiplier": str(configured_overhead),
            "adjusted_gas_estimate": gas_units_adjusted,
            "gas_cost_native": str(gas_native),
            "native_to_quote_rate": str(native_to_quote),
            "estimated_gas_cost_quote": str(gas_cost_quote),
            "gas_ceiling_quote": str(gas_ceiling),
            "gas_adjusted_net_profit_quote": str(gas_adjusted_net),
            "passed": passed,
            "timestamp": time.time(),
        }
        self.last_scan = result
        return result
