from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass

@dataclass
class Endpoint:
    url: str
    cooldown_until: float = 0.0
    failures: int = 0
    latency_ms: float = float("inf")

class RpcPool:
    """One bounded, failover-capable RPC pool. State is never shared across pools."""
    def __init__(self, urls, timeout=2.0, cooldown=15.0, concurrency=8):
        self.endpoints = [Endpoint(u) for u in dict.fromkeys(urls)]
        self.timeout = timeout
        self.cooldown = cooldown
        self.sem = asyncio.Semaphore(max(1, concurrency))

    def healthy(self):
        now = time.monotonic()
        return [e for e in self.endpoints if e.cooldown_until <= now]

    def mark_failure(self, endpoint):
        endpoint.failures += 1
        endpoint.cooldown_until = time.monotonic() + self.cooldown

    def mark_success(self, endpoint, latency_ms):
        endpoint.failures = 0
        endpoint.cooldown_until = 0.0
        endpoint.latency_ms = latency_ms

    async def call(self, transport, payload):
        errors = []
        candidates = sorted(self.healthy(), key=lambda x: (x.latency_ms, x.failures))
        for endpoint in candidates:
            start = time.monotonic()
            try:
                async with self.sem:
                    result = await asyncio.wait_for(
                        transport(endpoint.url, payload), timeout=self.timeout
                    )
                self.mark_success(endpoint, (time.monotonic() - start) * 1000)
                return result
            except Exception as exc:
                self.mark_failure(endpoint)
                errors.append(exc)
        raise RuntimeError(f"all RPC endpoints failed ({len(errors)})")

class IsolatedRpcFailover:
    """Owns a private RpcPool so one scanner's failover state cannot affect another."""
    def __init__(self, name: str, urls, timeout=2.0, cooldown=15.0, concurrency=4):
        if not name.strip():
            raise ValueError("RPC pool name is required")
        self.name = name
        self.pool = RpcPool(urls, timeout=timeout, cooldown=cooldown, concurrency=concurrency)

    async def call(self, transport, payload):
        return await self.pool.call(transport, payload)

class IsolatedRpcRegistry:
    """Maps each isolated scanner/venue to its own failover state."""
    def __init__(self, pools):
        names = [p.name for p in pools]
        if len(names) != len(set(names)):
            raise ValueError("duplicate isolated RPC pool")
        self.pools = {p.name: p for p in pools}

    def by_name(self, name):
        try:
            return self.pools[name]
        except KeyError:
            raise KeyError(name) from None
