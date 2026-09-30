import unittest
from decimal import Decimal

from options_engine.adapters.deriv import (
    DerivLiveExecutionBlocked,
    DerivOptionsDemo,
)


class DerivAdapterTests(unittest.TestCase):
    def test_demo_url_is_required(self):
        DerivOptionsDemo._assert_demo_url(
            "wss://api.derivws.com/trading/v1/options/ws/demo?otp=test"
        )
        with self.assertRaises(DerivLiveExecutionBlocked):
            DerivOptionsDemo._assert_demo_url(
                "wss://api.derivws.com/trading/v1/options/ws/real?otp=test"
            )

    def test_credentials_are_required_for_demo(self):
        adapter = DerivOptionsDemo(auth_token=None, account_id=None)
        with self.assertRaisesRegex(Exception, "DERIV_AUTH_TOKEN"):
            adapter._require_credentials()

    def test_timeframe_and_direction_contract_rules(self):
        self.assertEqual(Decimal("0.5"), Decimal("0.5"))
        with self.assertRaises(ValueError):
            self._validate_proposal_input("BUY", Decimal("0.5"), 60)
        with self.assertRaises(ValueError):
            self._validate_proposal_input("CALL", Decimal("0.5"), 120)
        with self.assertRaises(ValueError):
            self._validate_proposal_input("CALL", Decimal("1"), 60)
        with self.assertRaises(ValueError):
            self._validate_proposal_input("PUT", Decimal("0.5"), 300)

    @staticmethod
    def _validate_proposal_input(direction, stake, duration):
        direction = direction.upper()
        if direction not in {"CALL", "PUT"}:
            raise ValueError("direction must be CALL or PUT")
        if stake <= 0:
            raise ValueError("stake must be positive")
        if duration not in {60, 300}:
            raise ValueError("duration_seconds must be 60 or 300")


if __name__ == "__main__":
    unittest.main()
