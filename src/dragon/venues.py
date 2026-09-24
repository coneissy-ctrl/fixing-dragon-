"""Base-only venue registry for the production two-leg scanner.

The opportunity engine is hard-locked to Aerodrome and Uniswap V3 on Base.
No other venue is registered here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class Venue:
    name: str
    kind: str
    router: str
    factory: str = ""
    quoter: str = ""
    fee_tiers: tuple[int, ...] = ()
    enabled_by_default: bool = True
    note: str = ""


@dataclass(frozen=True)
class VenueResult:
    venue: str
    ok: bool
    value: Any = None
    error: str | None = None


EVM_VENUES: dict[int, tuple[Venue, ...]] = {
    8453: (
        Venue(
            name="Uniswap_V3",
            kind="v3",
            router="0x2626664c2603336E57B271c5C0b26F421741e481",
            factory="0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
            quoter="0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
            fee_tiers=(100, 500, 3000, 10000),
        ),
        Venue(
            name="Aerodrome",
            kind="stable",
            router="0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
            factory="0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
        ),
    ),
}


def venues_for(chain_id: int, *, include_disabled: bool = False) -> tuple[Venue, ...]:
    venues = EVM_VENUES.get(int(chain_id), ())
    if include_disabled:
        return venues
    return tuple(v for v in venues if v.enabled_by_default)


def venue_names(chain_id: int) -> tuple[str, ...]:
    return tuple(v.name for v in venues_for(chain_id))


def select_venues(
    chain_id: int,
    requested: tuple[str, ...] | list[str] | None,
) -> tuple[Venue, ...]:
    available = {v.name: v for v in venues_for(chain_id, include_disabled=True)}
    if not requested:
        return venues_for(chain_id)
    return tuple(
        available[name.strip()]
        for name in requested
        if name.strip() in available
    )


class IsolatedVenueScanner:
    """Runs one venue scanner as an independent failure domain."""

    def __init__(self, venue: str, scan: Callable[[], Any]):
        self.venue = venue
        self.scan = scan

    def run(self) -> VenueResult:
        try:
            return VenueResult(self.venue, True, self.scan(), None)
        except Exception as exc:
            return VenueResult(
                self.venue,
                False,
                None,
                f"{type(exc).__name__}: {exc}",
            )


class VenueScannerRegistry:
    """Keeps venue scanners independent; one failure never aborts the registry."""

    def __init__(self, scanners: list[IsolatedVenueScanner]):
        self.scanners = tuple(scanners)

    def scan_all(self) -> tuple[VenueResult, ...]:
        return tuple(scanner.run() for scanner in self.scanners)
