import os
from dataclasses import dataclass, field
from decimal import Decimal

def _dec(name, default): return Decimal(os.getenv(name, default))

def _str(name, default): return os.getenv(name, default)

def _bool(name, default='true'): return os.getenv(name, default).lower()=='true'

@dataclass(frozen=True)
class Settings:
    mode: str = field(default_factory=lambda:_str('OPTIONS_MODE','paper'))
    symbol: str = field(default_factory=lambda:_str('OPTIONS_SYMBOL','R_100'))
    stake: Decimal = field(default_factory=lambda:_dec('OPTIONS_STAKE','1'))
    max_stake: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_STAKE','10'))
    max_daily_loss: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_DAILY_LOSS','50'))
    dry_run: bool = field(default_factory=lambda:_bool('OPTIONS_DRY_RUN','true'))
    def validate(self):
        if self.mode not in {'paper','demo','live'}: raise ValueError('OPTIONS_MODE must be paper, demo, or live')
        if self.mode=='live' or not self.dry_run: raise ValueError('LIVE execution is intentionally locked in this initial build')
        if self.stake <= 0 or self.stake > self.max_stake: raise ValueError('invalid stake')
