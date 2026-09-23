"""Base-only live opportunity-universe scanner.

The scanner expands the token universe while preserving Dragon's hard execution
perimeter: Base mainnet (8453), Aerodrome and Uniswap V3, direct two-leg routes.
It discovers recently created pools around liquid anchors and caches the result
so block-log discovery never becomes the hot quote-path bottleneck.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock
from web3 import Web3

from .base_pool_discovery import discover_recent_base_tokens, CURATED_PAPER_BASE_TOKENS

BASE_CHAIN_ID = 8453


class BaseOpportunityUniverse:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: tuple[str, ...] = ()
        self._updated_at = 0.0
        self.refresh_seconds = max(30.0, float(os.getenv("DEX_UNIVERSE_REFRESH_SECONDS", "300")))
        self.max_tokens = max(5, min(250, int(os.getenv("DEX_UNIVERSE_MAX_TOKENS", "100"))))
        self.lookback_blocks = max(1000, min(250000, int(os.getenv("DEX_UNIVERSE_LOOKBACK_BLOCKS", "80000"))))
        self.chunk_blocks = max(500, min(10000, int(os.getenv("DEX_UNIVERSE_CHUNK_BLOCKS", "2000"))))

    @staticmethod
    def _valid(value: str) -> bool:
        try:
            Web3.to_checksum_address(value)
            return True
        except Exception:
            return False

    def tokens(self, adapter, quote_token: str, configured: list[str]) -> list[str]:
        if int(BASE_CHAIN_ID) != 8453:
            raise ValueError("Base opportunity universe requires chain 8453")

        now = time.monotonic()
        with self._lock:
            if self._tokens and now - self._updated_at < self.refresh_seconds:
                return list(self._tokens)

        anchors = []
        for value in [quote_token, *configured, *CURATED_PAPER_BASE_TOKENS]:
            if self._valid(value):
                checksummed = Web3.to_checksum_address(value)
                if checksummed.lower() != quote_token.lower():
                    anchors.append(checksummed)

        discovered: list[str] = []
        try:
            discovered = discover_recent_base_tokens(
                adapter,
                quote_token=quote_token,
                anchors=anchors,
                lookback_blocks=self.lookback_blocks,
                chunk_blocks=self.chunk_blocks,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            logging.warning("Base live universe discovery failed: %s: %s", exc)

        merged: list[str] = []
        seen: set[str] = set()
        for value in [*configured, *CURATED_PAPER_BASE_TOKENS, *discovered]:
            if not self._valid(value):
                continue
            checksummed = Web3.to_checksum_address(value)
            key = checksummed.lower()
            if key == quote_token.lower() or key in seen:
                continue
            seen.add(key)
            merged.append(checksummed)
            if len(merged) >= self.max_tokens:
                break

        with self._lock:
            self._tokens = tuple(merged)
            self._updated_at = now

        logging.info(
            "Base opportunity universe refreshed tokens=%s discovered=%s max=%s lookback_blocks=%s",
            len(merged), len(discovered), self.max_tokens, self.lookback_blocks,
        )
        return merged

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "chain_id": BASE_CHAIN_ID,
                "venues": ["Aerodrome", "Uniswap_V3"],
                "direct_legs_only": True,
                "triangular": False,
                "token_count": len(self._tokens),
                "updated_at": self._updated_at,
                "refresh_seconds": self.refresh_seconds,
                "max_tokens": self.max_tokens,
            }


BASE_UNIVERSE = BaseOpportunityUniverse()
