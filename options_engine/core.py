from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

class Mode(str, Enum):
    PAPER='paper'
    DEMO='demo'
    LIVE='live'

@dataclass(frozen=True)
class RiskLimits:
    max_stake: Decimal = Decimal('10')
    max_daily_loss: Decimal = Decimal('50')
    max_consecutive_losses: int = 5
    max_open_positions: int = 1
    cooldown_seconds: float = 2.0

class RiskEngine:
    def __init__(self, limits: RiskLimits):
        self.limits=limits; self.daily_pnl=Decimal('0'); self.consecutive_losses=0; self.open_positions=0
        self.halted=False
    def approve(self, stake: Decimal) -> tuple[bool,str]:
        if self.halted: return False,'HALTED'
        if stake <= 0 or stake > self.limits.max_stake: return False,'STAKE_LIMIT'
        if self.daily_pnl <= -self.limits.max_daily_loss: return False,'DAILY_LOSS_LIMIT'
        if self.consecutive_losses >= self.limits.max_consecutive_losses: return False,'LOSS_STREAK_LIMIT'
        if self.open_positions >= self.limits.max_open_positions: return False,'OPEN_POSITION_LIMIT'
        return True,'OK'
    def record(self, pnl: Decimal):
        self.daily_pnl += pnl
        if pnl < 0: self.consecutive_losses += 1
        else: self.consecutive_losses = 0
        if self.daily_pnl <= -self.limits.max_daily_loss: self.halted=True

class PaperBroker:
    def __init__(self): self.orders=[]; self.next_id=1
    def submit(self, symbol:str, direction:str, stake:Decimal, metadata=None):
        oid=f'PAPER-{self.next_id}'; self.next_id+=1
        order={'id':oid,'symbol':symbol,'direction':direction,'stake':str(stake),'status':'FILLED','metadata':metadata or {}}
        self.orders.append(order); return order
