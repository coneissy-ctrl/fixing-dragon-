from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Any

ALLOWED_VENUES = frozenset({"aerodrome", "uniswap_v3", "sushiswap"})


@dataclass(frozen=True)
class GasSnapshot:
    gas_price_wei: int
    gas_estimate: int
    execution_overhead_gas: int
    native_price_usd: Decimal
    gas_ceiling_usd: Decimal
    gas_cost_usd: Decimal
    gas_adjusted_net_profit_usd: Decimal


class IsolatedGasScanner:
    """Gas scanner with private state and failure boundary for one venue."""

    def __init__(self, venue: str, estimate_fn: Callable[[Any], int],
                 gas_price_fn: Callable[[Any], int],
                 native_price_fn: Callable[[Any], Decimal],
                 gas_ceiling_usd: Decimal = Decimal("0")):
        if venue not in ALLOWED_VENUES:
            raise ValueError("venue outside Dragon Base DEX perimeter")
        if gas_ceiling_usd < 0:
            raise ValueError("gas ceiling cannot be negative")
        self.venue = venue
        self._estimate_fn = estimate_fn
        self._gas_price_fn = gas_price_fn
        self._native_price_fn = native_price_fn
        self.gas_ceiling_usd = Decimal(gas_ceiling_usd)

    def scan(self, context: Any, gross_net_profit_usd: Decimal) -> GasSnapshot:
        gas_price = int(self._gas_price_fn(context))
        gas_estimate = int(self._estimate_fn(context))
        native_price = Decimal(self._native_price_fn(context))
        overhead = int(context.get("execution_overhead_gas", 0)) if isinstance(context, dict) else 0

        if gas_price < 0 or gas_estimate < 0 or overhead < 0 or native_price < 0:
            raise ValueError("gas inputs cannot be negative")

        total_gas = gas_estimate + overhead
        gas_cost_usd = (
            Decimal(gas_price) * Decimal(total_gas) * native_price
            / Decimal(10**18)
        )
        adjusted = Decimal(gross_net_profit_usd) - gas_cost_usd

        return GasSnapshot(
            gas_price, gas_estimate, overhead, native_price,
            self.gas_ceiling_usd, gas_cost_usd, adjusted
        )

    def passes(self, snapshot: GasSnapshot, min_net_profit_usd: Decimal) -> bool:
        return (
            snapshot.gas_cost_usd <= snapshot.gas_ceiling_usd
            and snapshot.gas_adjusted_net_profit_usd >= Decimal(min_net_profit_usd)
        )


def make_isolated_gas_scanners(
    estimate_fns: dict[str, Callable[[Any], int]],
    gas_price_fns: dict[str, Callable[[Any], int]],
    native_price_fns: dict[str, Callable[[Any], Decimal]],
    gas_ceiling_usd: Decimal = Decimal("0"),
) -> dict[str, IsolatedGasScanner]:
    missing = ALLOWED_VENUES - (set(estimate_fns) & set(gas_price_fns) & set(native_price_fns))
    if missing:
        raise ValueError(f"missing gas functions for venues: {sorted(missing)}")
    return {
        venue: IsolatedGasScanner(
            venue, estimate_fns[venue], gas_price_fns[venue],
            native_price_fns[venue], gas_ceiling_usd
        )
        for venue in ALLOWED_VENUES
    }
