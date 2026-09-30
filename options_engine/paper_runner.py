"""Finite paper binary lifecycle smoke runner. No real broker execution."""
from .config import Settings
from .core import RiskEngine, RiskLimits
from .paper_binary import PaperBinaryBroker
from .strategy import BinaryStrategy, Candle

def run():
    s=Settings(); s.validate()
    broker=PaperBinaryBroker()
    risk=RiskEngine(RiskLimits(max_stake=s.max_stake,max_daily_loss=s.max_daily_loss,max_consecutive_losses=s.max_consecutive_losses,max_open_positions=s.max_open_positions))
    out=[]
    for tf in s.timeframes:
        stake=s.stake_for(tf)
        n=30 if tf==1 else 25
        candles=[]; price=100.0
        for i in range(n+5):
            op=price; cl=price+0.20
            candles.append(Candle(i*60,op,cl+0.08,op-0.08,cl)); price=cl
        sig=BinaryStrategy(tf).generate(s.symbol,candles,stake)
        if sig is None or sig.stake != stake: raise RuntimeError(f'{tf}m signal/stake check failed')
        ok,why=risk.approve(stake)
        if not ok: raise RuntimeError(f'risk rejected: {why}')
        risk.open_positions += 1
        c=broker.open(sig.symbol,sig.direction,sig.stake,candles[-1].close,candles[-1].timestamp+sig.expiry_seconds)
        pnl=broker.settle(c,c.entry+0.10)
        risk.open_positions -= 1; risk.record(pnl)
        if s.stake_for(tf) != stake: raise RuntimeError(f'{tf}m stake changed')
        out.append(f'{tf}m {sig.direction} stake={stake} pnl={pnl} contract={c.id}')
    print('PAPER_RUN_OK')
    for x in out: print(x)
    print(f'daily_pnl={risk.daily_pnl}')
    print('live_execution=LOCKED')
    print('martingale=DISABLED')
    return 0

if __name__ == '__main__': raise SystemExit(run())
