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
    stake_1m: Decimal = field(default_factory=lambda:_dec('OPTIONS_STAKE_1M','0.5'))
    stake_5m: Decimal = field(default_factory=lambda:_dec('OPTIONS_STAKE_5M','2'))
    max_stake: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_STAKE','10'))
    max_daily_loss: Decimal = field(default_factory=lambda:_dec('OPTIONS_MAX_DAILY_LOSS','50'))
    max_consecutive_losses: int = field(default_factory=lambda:int(_str('OPTIONS_MAX_CONSECUTIVE_LOSSES','5')))
    max_open_positions: int = field(default_factory=lambda:int(_str('OPTIONS_MAX_OPEN_POSITIONS','1')))
    dry_run: bool = field(default_factory=lambda:_bool('OPTIONS_DRY_RUN','true'))
    martingale: bool = field(default_factory=lambda:_bool('OPTIONS_MARTINGALE','false'))

    def stake_for(self, timeframe_minutes: int) -> Decimal:
        if timeframe_minutes == 1: return self.stake_1m
        if timeframe_minutes == 5: return self.stake_5m
        raise ValueError('timeframe_minutes must be 1 or 5')

    def validate(self):
        if self.mode not in {'paper','demo','live'}:
            raise ValueError('OPTIONS_MODE must be paper, demo, or live')
        if self.mode=='live' or not self.dry_run:
            raise ValueError('LIVE execution is intentionally locked in this initial build')
        if set(self.timeframes) - {1,5} or not self.timeframes:
            raise ValueError('OPTIONS_TIMEFRAMES may contain only 1 and/or 5')
        if self.stake_1m <= 0 or self.stake_5m <= 0 or max(self.stake_1m,self.stake_5m) > self.max_stake:
            raise ValueError('invalid timeframe stake')
        if self.martingale:
            raise ValueError('Martingale is permanently disabled')
        if self.max_consecutive_losses < 1 or self.max_open_positions < 1:
            raise ValueError('invalid risk limits')
