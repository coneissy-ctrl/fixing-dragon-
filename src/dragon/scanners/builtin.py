from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

@dataclass(frozen=True)
class ScannerContext:
    """Normalized inputs supplied by the live quote/opportunity pipeline."""
    liquidity_ok: bool
    price_impact_ok: bool
    gas_quote: Decimal
    quote_age_seconds: float
    max_quote_age_seconds: float
    executable: bool
    net_profit_quote: Decimal
    min_net_profit_quote: Decimal
    simulation_ok: bool
    executable_amount_raw: int


def liquidity_scan(c: ScannerContext) -> bool:
    return bool(c.liquidity_ok)

def price_impact_scan(c: ScannerContext) -> bool:
    return bool(c.price_impact_ok)

def gas_scan(c: ScannerContext) -> Decimal:
    if c.gas_quote < 0:
        raise ValueError("gas cost cannot be negative")
    return c.gas_quote

def staleness_scan(c: ScannerContext) -> bool:
    if c.quote_age_seconds < 0 or c.max_quote_age_seconds < 0:
        raise ValueError("quote age cannot be negative")
    return c.quote_age_seconds <= c.max_quote_age_seconds

def execution_scan(c: ScannerContext) -> bool:
    return bool(c.executable)

def profit_scan(c: ScannerContext) -> Decimal:
    if c.net_profit_quote < c.min_net_profit_quote:
        raise ValueError("net profit below configured floor")
    return c.net_profit_quote

def simulation_scan(c: ScannerContext) -> bool:
    return bool(c.simulation_ok)

def sizing_scan(c: ScannerContext) -> int:
    if c.executable_amount_raw <= 0:
        raise ValueError("executable amount must be positive")
    return c.executable_amount_raw

BUILTIN_SCANNERS = (
    ("liquidity", liquidity_scan),
    ("price_impact", price_impact_scan),
    ("gas", gas_scan),
    ("staleness", staleness_scan),
    ("execution", execution_scan),
    ("profit", profit_scan),
    ("simulation", simulation_scan),
    ("sizing", sizing_scan),
)
