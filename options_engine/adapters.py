from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

class ExecutionAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def submit(self, symbol: str, direction: str, stake: Decimal, **kwargs: Any) -> dict: ...
    @abstractmethod
    async def close(self) -> None: ...

class PaperAdapter(ExecutionAdapter):
    def __init__(self): self.orders=[]
    async def connect(self): return None
    async def submit(self,symbol,direction,stake,**kwargs):
        order={'id':f'PAPER-{len(self.orders)+1}','symbol':symbol,'direction':direction,'stake':str(stake),'status':'FILLED','paper':True}
        self.orders.append(order); return order
    async def close(self): return None

class DemoOnlyAdapter(ExecutionAdapter):
    """Placeholder for broker-specific demo adapters.

    Real execution is intentionally not implemented here. Each broker must
    supply its own authentication, market-data, order, reconciliation and
    error semantics without sharing live credentials or endpoints.
    """
    async def connect(self): raise NotImplementedError('demo adapter not configured')
    async def submit(self,symbol,direction,stake,**kwargs): raise NotImplementedError('demo adapter not configured')
    async def close(self): return None
