from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float

class CandleAggregator:
    """Build completed 1m/5m candles from timestamped prices without look-ahead."""
    def __init__(self, timeframe_minutes: int):
        if timeframe_minutes not in (1, 5):
            raise ValueError("timeframe_minutes must be 1 or 5")
        self.period = timeframe_minutes * 60
        self._bucket: Optional[int] = None
        self._open = self._high = self._low = self._close = None

    def update(self, timestamp: int, price: float) -> Optional[Candle]:
        if price <= 0:
            raise ValueError("price must be positive")
        bucket = (int(timestamp) // self.period) * self.period
        if self._bucket is None:
            self._bucket = bucket
            self._open = self._high = self._low = self._close = float(price)
            return None
        if bucket == self._bucket:
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = float(price)
            return None
        completed = Candle(self._bucket, self._open, self._high, self._low, self._close)
        self._bucket = bucket
        self._open = self._high = self._low = self._close = float(price)
        return completed
