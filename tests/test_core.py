from decimal import Decimal
import asyncio,pytest
from dragon.calculator import CostModel,flash_loan_fee,net_profit
from dragon.config import Config
from dragon.routes import routes,validate_two_leg_route
from dragon.rpc import RpcPool

def test_routes_exact():
 assert routes()==(
  ("aerodrome","uniswap_v3"),
  ("uniswap_v3","aerodrome"),
  ("aerodrome","sushiswap"),
  ("sushiswap","aerodrome"),
  ("uniswap_v3","sushiswap"),
  ("sushiswap","uniswap_v3"),
 )

def test_rejects_bad_routes():
 with pytest.raises(ValueError): validate_two_leg_route("unknown","aerodrome","a","b")
 with pytest.raises(ValueError): validate_two_leg_route("aerodrome","aerodrome","a","b")
 
def test_sushiswap_is_independent_perimeter_member():
 validate_two_leg_route("sushiswap","aerodrome","a","b")
 validate_two_leg_route("uniswap_v3","sushiswap","a","b")

def test_rejects_same_token():
 with pytest.raises(ValueError): validate_two_leg_route("aerodrome","uniswap_v3","a","A")

def test_profit_and_fee():
 c=CostModel(Decimal(".10"),Decimal(".02"),Decimal(".01"))
 assert net_profit(Decimal("100"),Decimal("101"),c)==Decimal(".87")
 assert flash_loan_fee(Decimal("100"),5)==Decimal(".05")

def test_base_lock():
 assert Config.from_env().chain_id==8453

def test_rpc_failover():
 pool=RpcPool(("bad","good"),timeout=.1,cooldown=1)
 async def transport(url,payload):
  if url=="bad": raise RuntimeError("down")
  return {"ok":True}
 assert asyncio.run(pool.call(transport,{"method":"eth_blockNumber"}))=={"ok":True}
 assert pool.endpoints[0].failures==1
