from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Any

@dataclass(frozen=True)
class VenueResult:
    venue: str
    ok: bool
    value: Any = None
    error: str | None = None

class IsolatedVenueScanner:
    """Runs one venue scanner as an independent failure domain."""
    def __init__(self, venue: str, scan: Callable[[], Any]):
        self.venue = venue
        self.scan = scan

    def run(self) -> VenueResult:
        try:
            return VenueResult(self.venue, True, self.scan(), None)
        except Exception as exc:
            return VenueResult(self.venue, False, None, f"{type(exc).__name__}: {exc}")

class VenueScannerRegistry:
    """Keeps venue scanners independent; one failure never aborts the registry."""
    def __init__(self, scanners: list[IsolatedVenueScanner]):
        self.scanners = tuple(scanners)

    def scan_all(self) -> tuple[VenueResult, ...]:
        return tuple(scanner.run() for scanner in self.scanners)
