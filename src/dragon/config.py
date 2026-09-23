from __future__ import annotations
import os
from dataclasses import dataclass

CHAIN_ID=8453
ALLOWED_VENUES=frozenset({"aerodrome","uniswap_v3","sushiswap"})
MIN_NET_PROFIT_USD=0.005

def _bool(name,default=False):
 v=os.getenv(name); return default if v is None else v.strip().lower() in {"1","true","yes","on"}

def _urls(name):
 return tuple(x.strip() for x in os.getenv(name,"").split(",") if x.strip())

@dataclass(frozen=True)
class Config:
 chain_id:int=CHAIN_ID
 min_net_profit_usd:float=MIN_NET_PROFIT_USD
 rpc_urls:tuple[str,...]=()
 rpc_timeout_seconds:float=2.0
 rpc_cooldown_seconds:float=15.0
 rpc_concurrency:int=8
 poll_seconds:float=0.0
 flash_loan_enabled:bool=True
 flash_loan_fee_bps:int=0
 live_execution_enabled:bool=False

 @classmethod
 def from_env(cls):
  chain=int(os.getenv("DRAGON_CHAIN_ID",str(CHAIN_ID)))
  if chain!=CHAIN_ID: raise ValueError("Dragon is hard-locked to Base chain 8453")
  return cls(
   rpc_urls=_urls("BASE_RPC_URLS") or _urls("BASE_RPC_URL"),
   rpc_timeout_seconds=float(os.getenv("RPC_TIMEOUT_SECONDS","2.0")),
   rpc_cooldown_seconds=float(os.getenv("RPC_COOLDOWN_SECONDS","15.0")),
   rpc_concurrency=max(1,int(os.getenv("RPC_CONCURRENCY","8"))),
   poll_seconds=0.0,
   flash_loan_enabled=_bool("FLASH_LOAN_ENABLED",True),
   flash_loan_fee_bps=max(0,int(os.getenv("FLASH_LOAN_FEE_BPS","0"))),
   live_execution_enabled=_bool("LIVE_EXECUTION_ENABLED",False)
  )
