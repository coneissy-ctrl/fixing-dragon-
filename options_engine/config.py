import os
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class Settings:
    mode: str=os.getenv('OPTIONS_MODE','paper')
    symbol: str=os.getenv('OPTIONS_SYMBOL','R_100')
    stake: Decimal=Decimal(os.getenv('OPTIONS_STAKE','1'))
    max_stake: Decimal=Decimal(os.getenv('OPTIONS_MAX_STAKE','10'))
    max_daily_loss: Decimal=Decimal(os.getenv('OPTIONS_MAX_DAILY_LOSS','50'))
    dry_run: bool=os.getenv('OPTIONS_DRY_RUN','true').lower()=='true'
    def validate(self):
        if self.mode not in {'paper','demo','live'}: raise ValueError('OPTIONS_MODE must be paper, demo, or live')
        if self.mode=='live' or not self.dry_run: raise ValueError('LIVE execution is intentionally locked in this initial build')
        if self.stake <= 0 or self.stake > self.max_stake: raise ValueError('invalid stake')
