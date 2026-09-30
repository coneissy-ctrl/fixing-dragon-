import unittest
from decimal import Decimal
from options_engine.execution import PaperAdapter

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_paper_adapter(self):
        a=PaperAdapter(); await a.connect(); o=await a.submit('TEST','CALL',Decimal('1'))
        self.assertTrue(o['paper']); self.assertEqual(o['status'],'FILLED'); await a.close()

if __name__=='__main__': unittest.main()
