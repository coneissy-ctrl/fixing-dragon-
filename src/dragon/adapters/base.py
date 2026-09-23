from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class AdapterResult:
    venue: str
    ok: bool
    quote: Any = None
    error: str | None = None

class QuoteAdapter(ABC):
    venue: str

    @abstractmethod
    def quote(self, request: Any) -> Any:
        """Return one live quote or raise; never execute a transaction."""

    def safe_quote(self, request: Any) -> AdapterResult:
        try:
            return AdapterResult(self.venue, True, self.quote(request), None)
        except Exception as exc:
            return AdapterResult(self.venue, False, None, f"{type(exc).__name__}: {exc}")
