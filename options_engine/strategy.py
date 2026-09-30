from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class Signal:
    symbol: str
    direction: str
    stake: Decimal
    confidence: Decimal
    expiry_seconds: int
    reason: str

class Strategy:
    def generate(self, symbol: str, prices: list[float], stake: Decimal) -> Optional[Signal]:
        if len(prices) < 20: return None
        fast=sum(prices[-5:])/5; slow=sum(prices[-20:])/20
        confidence=Decimal(str(min(abs(fast-slow)/max(slow,1e-12)*1000,1)))
        if confidence < Decimal('0.25'): return None
        direction='CALL' if fast > slow else 'PUT'
        return Signal(symbol,direction,stake,confidence,60,'5/20 momentum')
