from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class PaperContract:
    id: str
    symbol: str
    direction: str
    stake: Decimal
    entry: float
    expiry_timestamp: int

class PaperBinaryBroker:
    """Fixed-payout paper broker; stake never changes after a loss."""
    def __init__(self, payout: Decimal = Decimal("0.80")):
        if payout <= 0 or payout >= 1:
            raise ValueError("payout must be between 0 and 1")
        self.payout = payout
        self.contracts = []
        self._next_id = 1

    def open(self, symbol, direction, stake, entry, expiry_timestamp):
        if direction not in {"CALL", "PUT"} or stake <= 0 or entry <= 0:
            raise ValueError("invalid binary contract")
        contract = PaperContract(f"PAPER-BIN-{self._next_id}", symbol, direction, stake, entry, expiry_timestamp)
        self._next_id += 1
        self.contracts.append(contract)
        return contract

    def settle(self, contract: PaperContract, exit_price: float) -> Decimal:
        if exit_price <= 0:
            raise ValueError("exit_price must be positive")
        if exit_price == contract.entry:
            return Decimal("0")
        won = exit_price > contract.entry if contract.direction == "CALL" else exit_price < contract.entry
        return contract.stake * self.payout if won else -contract.stake
