"""Profit-based compounding manager for Deriv options execution.

The manager changes stake size only from realized profits. It never martingales:
a loss resets the compounding state, and every live stake remains inside the
configured min/max bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


def _d(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass
class CompoundingSnapshot:
    enabled: bool
    trigger_wins: int
    frequency_trades: int
    profit_allocation_pct: Decimal
    max_stake: Decimal
    base_stake: Decimal
    current_stake: Decimal
    profit_pool: Decimal
    consecutive_wins: int
    trades_since_compound: int
    next_compound_in: int | None
    compound_count: int
    last_result: str | None


class CompoundingEngine:
    """Realized-profit compounding with a hard stake ceiling.

    After trigger_wins consecutive wins, a compound event becomes eligible every
    frequency_trades trades. At an event, allocation_pct of the unallocated
    realized-profit pool is added to the base stake. A loss resets everything.
    """

    def __init__(
        self,
        *,
        base_stake: Decimal,
        enabled: bool = True,
        trigger_wins: int = 5,
        frequency_trades: int = 2,
        profit_allocation_pct: Decimal = Decimal("0.50"),
        max_stake: Decimal = Decimal("5"),
        min_stake: Decimal | None = None,
    ) -> None:
        self.enabled = enabled
        self.trigger_wins = max(1, int(trigger_wins))
        self.frequency_trades = max(1, int(frequency_trades))
        self.profit_allocation_pct = max(Decimal("0"), min(Decimal("1"), profit_allocation_pct))
        self.base_stake = base_stake
        self.max_stake = max(base_stake, max_stake)
        self.min_stake = min_stake if min_stake is not None else base_stake
        self.current_stake = base_stake
        self.profit_pool = Decimal("0")
        self.consecutive_wins = 0
        self.trades_since_compound = 0
        self.compound_count = 0
        self.last_result: str | None = None

    def _quantize(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    def record_result(self, *, won: bool, profit: Decimal) -> Decimal:
        profit = _d(profit)
        self.last_result = "WIN" if won else "LOSS"

        if not self.enabled:
            self.current_stake = self.base_stake
            return self.current_stake

        if not won:
            self.consecutive_wins = 0
            self.trades_since_compound = 0
            self.profit_pool = Decimal("0")
            self.current_stake = self.base_stake
            return self.current_stake

        self.consecutive_wins += 1
        if profit > 0:
            self.profit_pool += profit

        if self.consecutive_wins < self.trigger_wins:
            self.current_stake = self.base_stake
            return self.current_stake

        self.trades_since_compound += 1
        if self.trades_since_compound < self.frequency_trades:
            self.current_stake = self.base_stake
            return self.current_stake

        allocated = self.profit_pool * self.profit_allocation_pct
        candidate = self.base_stake + allocated
        self.current_stake = min(self.max_stake, max(self.min_stake, self._quantize(candidate)))
        self.profit_pool = max(Decimal("0"), self.profit_pool - allocated)
        self.trades_since_compound = 0
        self.compound_count += 1
        return self.current_stake

    def next_stake(self) -> Decimal:
        return min(self.max_stake, max(self.min_stake, self.current_stake)) if self.enabled else self.base_stake

    def snapshot(self) -> CompoundingSnapshot:
        next_in = None
        if self.enabled and self.consecutive_wins >= self.trigger_wins:
            next_in = max(1, self.frequency_trades - self.trades_since_compound)
        return CompoundingSnapshot(
            enabled=self.enabled,
            trigger_wins=self.trigger_wins,
            frequency_trades=self.frequency_trades,
            profit_allocation_pct=self.profit_allocation_pct,
            max_stake=self.max_stake,
            base_stake=self.base_stake,
            current_stake=self.next_stake(),
            profit_pool=self.profit_pool,
            consecutive_wins=self.consecutive_wins,
            trades_since_compound=self.trades_since_compound,
            next_compound_in=next_in,
            compound_count=self.compound_count,
            last_result=self.last_result,
        )
