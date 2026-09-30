from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float

@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    stake: Decimal
    confidence: Decimal
    timeframe_minutes: int
    expiry_seconds: int
    candle_timestamp: int
    reason: str

class BinaryStrategy:
    """Deterministic 1m/5m binary strategy. Fixed stake; never changes stake after losses."""

    def __init__(self, timeframe_minutes: int):
        if timeframe_minutes not in (1, 5):
            raise ValueError("timeframe_minutes must be 1 or 5")
        self.timeframe_minutes = timeframe_minutes
        self._last_signal_candle: Optional[int] = None

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        k = 2.0 / (period + 1)
        value = values[0]
        for item in values[1:]:
            value = item * k + value * (1 - k)
        return value

    @staticmethod
    def _atr(candles: list[Candle], period: int = 14) -> float:
        if len(candles) < period + 1:
            return 0.0
        trs=[]
        for prev, cur in zip(candles[-period-1:-1], candles[-period:]):
            trs.append(max(cur.high-cur.low, abs(cur.high-prev.close), abs(cur.low-prev.close)))
        return sum(trs)/len(trs)

    def generate(self, symbol: str, candles: list[Candle], stake: Decimal) -> Optional[Signal]:
        minimum = 30 if self.timeframe_minutes == 1 else 25
        if len(candles) < minimum or stake <= 0:
            return None

        current = candles[-1]
        if self._last_signal_candle == current.timestamp:
            return None

        closes=[c.close for c in candles]
        fast=self._ema(closes[-20:], 5)
        slow=self._ema(closes[-20:], 12)
        atr=self._atr(candles)
        if atr <= 0:
            return None

        body=abs(current.close-current.open)
        if body < atr * 0.20:
            return None

        # Require trend, candle direction, and momentum alignment.
        if current.close > current.open and fast > slow and current.close > fast:
            direction="CALL"
        elif current.close < current.open and fast < slow and current.close < fast:
            direction="PUT"
        else:
            return None

        separation=abs(fast-slow)
        confidence=Decimal(str(min(separation / max(atr, 1e-12), 1.0)))
        if confidence < Decimal("0.20"):
            return None

        self._last_signal_candle=current.timestamp
        return Signal(
            symbol=symbol,
            direction=direction,
            stake=stake,
            confidence=confidence,
            timeframe_minutes=self.timeframe_minutes,
            expiry_seconds=self.timeframe_minutes * 60,
            candle_timestamp=current.timestamp,
            reason=f"{self.timeframe_minutes}m EMA5/EMA12 + momentum + ATR filter",
        )

# Backward-compatible default: 1-minute strategy.
class Strategy(BinaryStrategy):
    def __init__(self, timeframe_minutes: int = 1):
        super().__init__(timeframe_minutes)
