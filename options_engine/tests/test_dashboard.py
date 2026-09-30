import unittest
from options_engine.dashboard import DashboardState


class DashboardTests(unittest.TestCase):
    def test_payload_is_safe_and_read_only(self):
        p = DashboardState().payload()
        self.assertFalse(p["real_money"])
        self.assertEqual(p["execution"], "DEMO_ONLY / LOCKED")
        self.assertEqual(p["stakes"]["1m"], "0.50")
        self.assertEqual(p["stakes"]["5m"], "2.00")
        self.assertFalse(p["martingale"])


if __name__ == "__main__":
    unittest.main()
