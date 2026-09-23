from dataclasses import dataclass
from decimal import Decimal
@dataclass(frozen=True)
class CostModel:
 gas_quote:Decimal=Decimal("0"); flash_loan_fee_quote:Decimal=Decimal("0"); safety_buffer_quote:Decimal=Decimal("0")
def net_profit(input_quote,final_quote,costs): return final_quote-input_quote-costs.gas_quote-costs.flash_loan_fee_quote-costs.safety_buffer_quote
def flash_loan_fee(principal_quote,fee_bps):
 if principal_quote<0 or fee_bps<0: raise ValueError("principal and fee must be non-negative")
 return principal_quote*Decimal(fee_bps)/Decimal(10000)
