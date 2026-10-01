"""Optional Amplitude analytics for the Deriv Gold options engine.

Analytics is deliberately fail-open: if Amplitude is unavailable or not configured,
trading continues normally. Set AMPLITUDE_API_KEY in Render to enable it.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

AMPLITUDE_ENDPOINT = "https://api2.amplitude.com/2/httpapi"


class AmplitudeAnalytics:
    def __init__(self) -> None:
        self.api_key = os.getenv("AMPLITUDE_API_KEY")
        self.enabled = bool(self.api_key)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self.enabled and (self._worker is None or self._worker.done()):
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._send(event)
            except Exception as exc:
                print(
                    f"AMPLITUDE_ERROR type={type(exc).__name__} error={exc}",
                    flush=True,
                )
            finally:
                self._queue.task_done()

    async def _send(self, event: dict[str, Any]) -> None:
        if not self.api_key:
            return
        payload = {
            "api_key": self.api_key,
            "events": [event],
        }
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(AMPLITUDE_ENDPOINT, json=payload)
            response.raise_for_status()

    def track(
        self,
        event_type: str,
        *,
        user_id: str = "deriv-options-engine",
        event_properties: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        event = {
            "user_id": user_id,
            "event_type": event_type,
            "time": int(time.time() * 1000),
            "event_properties": event_properties or {},
        }
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            print("AMPLITUDE_DROP queue_full", flush=True)

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
