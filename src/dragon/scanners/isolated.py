from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class AnalysisResult:
    name: str
    ok: bool
    value: Any = None
    error: str | None = None

class IsolatedAnalysisScanner:
    """One analysis concern with its own failure boundary."""
    def __init__(self, name: str, scan: Callable[[Any], Any]):
        if not name.strip():
            raise ValueError("scanner name is required")
        self.name = name
        self.scan = scan

    def run(self, context: Any) -> AnalysisResult:
        try:
            return AnalysisResult(self.name, True, self.scan(context), None)
        except Exception as exc:
            return AnalysisResult(self.name, False, None, f"{type(exc).__name__}: {exc}")

class AnalysisScannerRegistry:
    """Runs every analysis scanner independently; one failure is isolated."""
    def __init__(self, scanners: list[IsolatedAnalysisScanner]):
        names = [s.name for s in scanners]
        if len(names) != len(set(names)):
            raise ValueError("duplicate analysis scanner")
        self.scanners = tuple(scanners)

    def scan_all(self, context: Any) -> tuple[AnalysisResult, ...]:
        return tuple(scanner.run(context) for scanner in self.scanners)
