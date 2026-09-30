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
    timeframes: tuple[int,...] = field(default_factory=lambda: tuple(int(x) for x in _str('OPTIONS_TIMEFRAMES','1,5').split(',') if x.strip()))
    stake: Decimal = field(default_factory=lambda:_dec('OPTIONS_STAKE','1'))
    max_stake: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_STAKE','10'))
    max_daily_loss: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_DAILY_LOSS','50'))
    max_consecutive_losses: int = field(default_factory=lambda:int(_str('OPTIONS_MAX_CONSECUTIVE_LOSSES','5')))
    max_open_positions: int = field(default_factory=lambda:int(_str('OPTIONS_MAX_OPEN_POSITIONS','1')))
    dry_run: bool = field(default_factory=lambda:_bool('OPTIONS_DRY_RUN','true'))
    martingale: bool = field(default_factory=lambda:_bool('OPTIONS_MARTINGALE','false'))

    def validate(self):
        if self.mode not in {'paper','demo','live'}:
            raise ValueError('OPTIONS_MODE must be paper, demo, or live')
        if self.mode=='live' or not self.dry_run:
            raise ValueError('LIVE execution is intentionally locked in this initial build')
        if set(self.timeframes) - {1,5} or not self.timeframes:
            raise ValueError('OPTIONS_TIMEFRAMES may contain only 1 and/or 5')
        if self.stake <= 0 or self.stake > self.max_stake:
            raise ValueError('invalid stake')
        if self.martingale:
            raise ValueError('Martingale is permanently disabled')
        if self.max_consecutive_losses < 1 or self.max_open_positions < 1:
            raise ValueError('invalid risk limits')
