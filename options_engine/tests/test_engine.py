import unittest
from decimal import Decimal
from options_engine.core import RiskEngine,RiskLimits,PaperBroker
from options_engine.strategy import Strategy
from options_engine.config import Settings
class EngineTests(unittest.TestCase):
    def test_paper_order(self): self.assertEqual(PaperBroker().submit('R_100','CALL',Decimal('1'))['status'],'FILLED')
    def test_risk_limit(self): self.assertFalse(RiskEngine(RiskLimits(max_stake=Decimal('10'))).approve(Decimal('11'))[0])
    def test_loss_halt(self):
        r=RiskEngine(RiskLimits(max_daily_loss=Decimal('5'))); r.record(Decimal('-5')); self.assertTrue(r.halted)
    def test_strategy_needs_data(self): self.assertIsNone(Strategy().generate('R_100',[1,2],Decimal('1')))
    def test_live_locked(self):
        with self.assertRaises(ValueError): Settings(mode='live').validate()
if __name__=='__main__': unittest.main()
