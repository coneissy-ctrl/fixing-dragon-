from __future__ import annotations
import asyncio,time
from dataclasses import dataclass
@dataclass
class Endpoint:
 url:str; cooldown_until:float=0.0; failures:int=0; latency_ms:float=float("inf")
class RpcPool:
 def __init__(self,urls,timeout=2.0,cooldown=15.0,concurrency=8): self.endpoints=[Endpoint(u) for u in dict.fromkeys(urls)]; self.timeout=timeout; self.cooldown=cooldown; self.sem=asyncio.Semaphore(max(1,concurrency))
 def healthy(self):
  now=time.monotonic(); return [e for e in self.endpoints if e.cooldown_until<=now]
 def mark_failure(self,e): e.failures+=1; e.cooldown_until=time.monotonic()+self.cooldown
 def mark_success(self,e,latency_ms): e.failures=0; e.cooldown_until=0.0; e.latency_ms=latency_ms
 async def call(self,transport,payload):
  errors=[]
  for e in sorted(self.healthy(),key=lambda x:(x.latency_ms,x.failures)):
   start=time.monotonic()
   try:
    async with self.sem: result=await asyncio.wait_for(transport(e.url,payload),timeout=self.timeout)
    self.mark_success(e,(time.monotonic()-start)*1000); return result
   except Exception as exc: self.mark_failure(e); errors.append(exc)
  raise RuntimeError(f"all RPC endpoints failed ({len(errors)})")
