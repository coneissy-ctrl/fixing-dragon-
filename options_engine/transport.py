import asyncio, json, logging, time
from typing import Any, Callable
log=logging.getLogger(__name__)
class SafeWS:
    def __init__(self,url:str,connect:Callable,max_retries:int=8): self.url=url; self.connect=connect; self.max_retries=max_retries; self.ws=None; self.last_message=0.0
    async def run(self,handler:Callable[[dict],Any]):
        delay=1.0
        for _ in range(self.max_retries):
            try:
                self.ws=await self.connect(self.url); self.last_message=time.monotonic(); delay=1.0
                async for raw in self.ws:
                    self.last_message=time.monotonic(); await handler(json.loads(raw))
            except asyncio.CancelledError: raise
            except Exception as exc:
                log.warning('ws reconnect %s: %s',self.url,exc); await asyncio.sleep(delay); delay=min(delay*2,30)
        raise RuntimeError(f'websocket retry budget exhausted: {self.url}')
