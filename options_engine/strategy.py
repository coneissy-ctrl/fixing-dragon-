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
    analysis: dict[str, float | str] | None = None

class BinaryStrategy:
    """Regular-options Gold technical analysis using trend, RSI, MACD, ATR and S/R."""

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
    def _rsi(values: list[float], period: int = 14) -> float:
        if len(values) < period + 1:
            return 50.0
        gains=[]; losses=[]
        for a,b in zip(values[-period-1:-1], values[-period:]):
            change=b-a
            gains.append(max(change,0.0)); losses.append(max(-change,0.0))
        avg_gain=sum(gains)/period; avg_loss=sum(losses)/period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs=avg_gain/avg_loss
        return 100.0-(100.0/(1.0+rs))

    @staticmethod
    def _macd(values: list[float]) -> tuple[float,float,float]:
        if len(values) < 26:
            return 0.0,0.0,0.0
        fast=BinaryStrategy._ema(values,12); slow=BinaryStrategy._ema(values,26)
        macd=fast-slow
        history=[]
        for i in range(26,len(values)+1):
            w=values[:i]
            history.append(BinaryStrategy._ema(w,12)-BinaryStrategy._ema(w,26))
        signal=BinaryStrategy._ema(history[-9:],9)
        return macd,signal,macd-signal

    @staticmethod
    def _atr(candles: list[Candle], period: int = 14) -> float:
        if len(candles) < period + 1:
            return 0.0
        trs=[]
        for prev, cur in zip(candles[-period-1:-1], candles[-period:]):
            trs.append(max(cur.high-cur.low, abs(cur.high-prev.close), abs(cur.low-prev.close)))
        return sum(trs)/len(trs)

    def generate(self, symbol: str, candles: list[Candle], stake: Decimal) -> Optional[Signal]:
        minimum = 35 if self.timeframe_minutes == 1 else 30
        if len(candles) < minimum or stake <= 0:
            return None

        current = candles[-1]
        if self._last_signal_candle == current.timestamp:
            return None

        closes=[c.close for c in candles]
        fast=self._ema(closes[-20:], 5)
        slow=self._ema(closes[-20:], 12)
        atr=self._atr(candles)
        rsi=self._rsi(closes,14)
        macd,macd_signal,macd_hist=self._macd(closes)
        recent=candles[-20:]
        support=min(c.low for c in recent); resistance=max(c.high for c in recent)
        if atr <= 0:
            return None

        body=abs(current.close-current.open)
        if body < atr * 0.20:
            return None

        # Require trend, candle direction, and momentum alignment.
        bullish=current.close > current.open and fast > slow and current.close > fast and macd_hist > 0 and rsi >= 52
        bearish=current.close < current.open and fast < slow and current.close < fast and macd_hist < 0 and rsi <= 48
        if bullish:
            direction="CALL"
        elif bearish:
            direction="PUT"
        else:
            return None

        separation=abs(fast-slow)
        trend_score=min(separation / max(atr,1e-12),1.0)
        momentum_score=min(abs(macd_hist) / max(atr,1e-12),1.0)
        rsi_score=min(abs(rsi-50.0)/20.0,1.0)
        confidence=Decimal(str(min(1.0,0.45*trend_score+0.35*momentum_score+0.20*rsi_score)))
        if confidence < Decimal("0.30"):
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
            reason=f"{self.timeframe_minutes}m EMA9/EMA21 + RSI + MACD + ATR + S/R",
            analysis={"ema_fast":round(fast,6),"ema_slow":round(slow,6),"rsi":round(rsi,2),"macd_hist":round(macd_hist,6),"atr":round(atr,6),"support":round(support,6),"resistance":round(resistance,6)},
        )

# Backward-compatible default: 1-minute strategy.
class Strategy(BinaryStrategy):
    def __init__(self, timeframe_minutes: int = 1):
        super().__init__(timeframe_minutes)
