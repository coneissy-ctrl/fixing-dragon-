import unittest
from options_engine.transport import SafeWS
class TransportTests(unittest.TestCase):
    def test_constructs_with_retry_budget(self):
        ws=SafeWS('wss://example.invalid',lambda url:None,max_retries=3)
        self.assertEqual(ws.max_retries,3)
if __name__=='__main__': unittest.main()
