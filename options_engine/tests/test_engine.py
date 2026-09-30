import unittest
from decimal import Decimal
from options_engine.core import RiskEngine,RiskLimits,PaperBroker
from options_engine.strategy import Candle,Strategy
from options_engine.config import Settings

def candles(direction="up", n=40):
    out=[]; price=100.0
    for i in range(n):
        o=price; c=price+1.0 if direction=="up" else price-1.0
        out.append(Candle(i,o,max(o,c)+0.2,min(o,c)-0.2,c)); price=c
    return out

class EngineTests(unittest.TestCase):
    def test_paper_order(self):
        self.assertEqual(PaperBroker().submit('R_100','CALL',Decimal('1'))['status'],'FILLED')
    def test_risk_limit(self):
        self.assertFalse(RiskEngine(RiskLimits(max_stake=Decimal('10'))).approve(Decimal('11'))[0])
    def test_loss_halt(self):
        r=RiskEngine(RiskLimits(max_daily_loss=Decimal('5'))); r.record(Decimal('-5')); self.assertTrue(r.halted)
    def test_one_minute_signal(self):
        s=Strategy(1).generate('R_100',candles('up'),Decimal('1'))
        self.assertIsNotNone(s); self.assertEqual(s.direction,'CALL'); self.assertEqual(s.expiry_seconds,60)
    def test_five_minute_signal(self):
        s=Strategy(5).generate('R_100',candles('down'),Decimal('1'))
        self.assertIsNotNone(s); self.assertEqual(s.direction,'PUT'); self.assertEqual(s.expiry_seconds,300)
    def test_one_signal_per_candle(self):
        strategy=Strategy(1); data=candles('up')
        self.assertIsNotNone(strategy.generate('R_100',data,Decimal('1')))
        self.assertIsNone(strategy.generate('R_100',data,Decimal('1')))
    def test_martingale_rejected(self):
        with self.assertRaises(ValueError): Settings(martingale=True).validate()
    def test_timeframes(self):
        s=Settings(); s.validate(); self.assertEqual(s.timeframes,(1,5))
    def test_live_locked(self):
        with self.assertRaises(ValueError): Settings(mode='live').validate()

if __name__=='__main__': unittest.main()
