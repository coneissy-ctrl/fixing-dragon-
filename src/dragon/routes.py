ALLOWED=frozenset({"aerodrome","uniswap_v3"})
def validate_two_leg_route(first,second,token_a,token_b):
 if first not in ALLOWED or second not in ALLOWED: raise ValueError("venue outside Dragon Base DEX perimeter")
 if first==second: raise ValueError("route must cross venues")
 if token_a.lower()==token_b.lower(): raise ValueError("same-token route is not an arbitrage")
def routes(): return (("aerodrome","uniswap_v3"),("uniswap_v3","aerodrome"))
