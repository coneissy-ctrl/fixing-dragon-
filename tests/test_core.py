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

def test_venue_scanners_are_isolated():
 from dragon.venues import IsolatedVenueScanner, VenueScannerRegistry
 good=IsolatedVenueScanner("aerodrome",lambda: "quote")
 bad=IsolatedVenueScanner("sushiswap",lambda: (_ for _ in ()).throw(RuntimeError("rpc down")))
 results=VenueScannerRegistry([good,bad]).scan_all()
 assert results[0].ok and results[0].value=="quote"
 assert not results[1].ok and "rpc down" in results[1].error

def test_quote_adapters_are_isolated():
 from dragon.adapters.aerodrome import AerodromeAdapter
 from dragon.adapters.uniswap_v3 import UniswapV3Adapter
 from dragon.adapters.sushiswap import SushiSwapAdapter
 from dragon.adapters.registry import IsolatedAdapterRegistry
 good=AerodromeAdapter(lambda _: "aero")
 bad=UniswapV3Adapter(lambda _: (_ for _ in ()).throw(RuntimeError("uniswap rpc down")))
 sushi=SushiSwapAdapter(lambda _: "sushi")
 results=IsolatedAdapterRegistry([good,bad,sushi]).quote_all({})
 assert [(r.venue,r.ok,r.quote) for r in results]==[
  ("aerodrome",True,"aero"),
  ("uniswap_v3",False,None),
  ("sushiswap",True,"sushi"),
 ]


def test_analysis_scanners_are_isolated():
 from dragon.scanners.isolated import IsolatedAnalysisScanner, AnalysisScannerRegistry
 good=IsolatedAnalysisScanner("liquidity",lambda c: True)
 bad=IsolatedAnalysisScanner("gas",lambda c: (_ for _ in ()).throw(RuntimeError("gas unavailable")))
 other=IsolatedAnalysisScanner("staleness",lambda c: True)
 results=AnalysisScannerRegistry([good,bad,other]).scan_all({})
 assert [(x.name,x.ok,x.value) for x in results]==[
  ("liquidity",True,True),
  ("gas",False,None),
  ("staleness",True,True),
 ]

def test_builtin_scanner_set_is_explicit():
 from dragon.scanners.builtin import BUILTIN_SCANNERS
 assert tuple(name for name, _ in BUILTIN_SCANNERS)==(
  "liquidity","price_impact","gas","staleness",
  "execution","profit","simulation","sizing",
 )

def test_profit_scanner_enforces_floor():
 from dragon.scanners.builtin import ScannerContext, profit_scan
 c=ScannerContext(True,True,Decimal("0.01"),0,1,True,Decimal("0.006"),Decimal("0.005"),True,1)
 assert profit_scan(c)==Decimal("0.006")
 c2=ScannerContext(True,True,Decimal("0.01"),0,1,True,Decimal("0.004"),Decimal("0.005"),True,1)
 with pytest.raises(ValueError): profit_scan(c2)


def test_rpc_failover_state_is_isolated():
 from dragon.rpc import IsolatedRpcFailover, IsolatedRpcRegistry
 aero=IsolatedRpcFailover("aerodrome",("a1","a2"))
 uni=IsolatedRpcFailover("uniswap_v3",("u1","u2"))
 registry=IsolatedRpcRegistry([aero,uni])
 aero.pool.mark_failure(aero.pool.endpoints[0])
 assert aero.pool.endpoints[0].failures==1
 assert uni.pool.endpoints[0].failures==0
 assert registry.by_name("aerodrome") is aero
 assert registry.by_name("uniswap_v3") is uni
