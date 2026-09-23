from decimal import Decimal
from .calculator import CostModel,net_profit
from .models import Opportunity,Quote
from .routes import routes,validate_two_leg_route
class OpportunityScanner:
 def __init__(self,min_net_profit=Decimal("0.005")): self.min_net_profit=Decimal(min_net_profit)
 def evaluate(self,first:Quote,second:Quote,input_quote,costs:CostModel):
  validate_two_leg_route(first.venue,second.venue,first.token_in,first.token_out)
  if first.token_out.lower()!=second.token_in.lower(): return None
  profit=net_profit(Decimal(input_quote),Decimal(second.amount_out_raw),costs)
  if profit<self.min_net_profit:return None
  return Opportunity(first.venue,second.venue,first.token_in,first.token_out,first.amount_in_raw,second.amount_out_raw,profit)
 @staticmethod
 def allowed_routes(): return routes()
