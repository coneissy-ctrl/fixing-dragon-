from dataclasses import dataclass
from decimal import Decimal
@dataclass(frozen=True)
class Quote:
 venue:str; token_in:str; token_out:str; amount_in_raw:int; amount_out_raw:int; gas_estimate:int=0
@dataclass(frozen=True)
class Opportunity:
 buy_venue:str; sell_venue:str; token_in:str; token_mid:str; amount_in_raw:int; final_amount_raw:int; net_profit_quote:Decimal
