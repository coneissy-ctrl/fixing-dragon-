"""Multi-chain registry for the Dragon cross-DEX arbitrage engine.

Each entry declares everything the adapters need to talk to a chain: its chain
id, the native gas token, the default wrapped-native address, the wrapped-native
decimals, and which environment variables hold RPC endpoints.

Only chains with a verified on-chain DEX venue are listed as executable.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ChainSpec:
    chain_id: int
    name: str
    family: str
    native_symbol: str
    wrapped_native: str
    wrapped_native_decimals: int
    explorer: str
    rpc_env: str
    rpc_fallback_env: str
    default_rpc: str = ""


EVM_CHAINS: dict[int, ChainSpec] = {
    1: ChainSpec(1,"ethereum","evm","ETH","0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",18,"https://etherscan.io","ETHEREUM_RPC_URL","ETHEREUM_RPC_URLS","https://ethereum-rpc.publicnode.com"),
    56: ChainSpec(56,"bnb","evm","BNB","0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",18,"https://bscscan.com","BNB_RPC_URL","BNB_RPC_URLS","https://bsc-rpc.publicnode.com"),
    43114: ChainSpec(43114,"avalanche","evm","AVAX","0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",18,"https://snowtrace.io","AVALANCHE_RPC_URL","AVALANCHE_RPC_URLS","https://avalanche-c-chain-rpc.publicnode.com"),
    84532: ChainSpec(84532,"base-sepolia","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://sepolia.basescan.org","BASE_SEPOLIA_RPC_URL","BASE_SEPOLIA_RPC_URLS","https://sepolia.base.org"),
    8453: ChainSpec(8453,"base","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://basescan.org","DEX_RPC_URL","DEX_RPC_URLS","https://base-rpc.publicnode.com"),
    42161: ChainSpec(42161,"arbitrum","evm","ETH","0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",18,"https://arbiscan.io","ARBITRUM_RPC_URL","ARBITRUM_RPC_URLS","https://arbitrum-one-rpc.publicnode.com"),
    10: ChainSpec(10,"optimism","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://optimistic.etherscan.io","OPTIMISM_RPC_URL","OPTIMISM_RPC_URLS","https://optimism-rpc.publicnode.com"),
    137: ChainSpec(137,"polygon","evm","POL","0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",18,"https://polygonscan.com","POLYGON_RPC_URL","POLYGON_RPC_URLS","https://polygon-bor-rpc.publicnode.com"),
    130: ChainSpec(130,"unichain","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://uniscan.xyz","UNICHAIN_RPC_URL","UNICHAIN_RPC_URLS","https://unichain-rpc.publicnode.com"),
    324: ChainSpec(324,"zksync","evm","ETH","0x5AEa5775959fBC2557Cc8789bC1bf90A239D9a91",18,"https://explorer.zksync.io","ZKSYNC_RPC_URL","ZKSYNC_RPC_URLS","https://mainnet.era.zksync.io"),
    7777777: ChainSpec(7777777,"zora","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://explorer.zora.energy","ZORA_RPC_URL","ZORA_RPC_URLS","https://rpc.zora.energy"),
    480: ChainSpec(480,"worldchain","evm","ETH","0x4200000000000000000000000000000000000006",18,"https://worldscan.org","WORLDCHAIN_RPC_URL","WORLDCHAIN_RPC_URLS","https://worldchain-mainnet.g.alchemy.com/public"),
    42220: ChainSpec(42220,"celo","evm","CELO","0x471EcE3750Da237f93B8E339c536989b8978a438",18,"https://celoscan.io","CELO_RPC_URL","CELO_RPC_URLS","https://celo-rpc.publicnode.com"),
    59144: ChainSpec(59144,"linea","evm","ETH","0xe5D7C2a44FfDDf6b295A15c148167daaAf5CF34f",18,"https://lineascan.build","LINEA_RPC_URL","LINEA_RPC_URLS","https://linea-rpc.publicnode.com"),
    534352: ChainSpec(534352,"scroll","evm","ETH","0x5300000000000000000000000000000000000004",18,"https://scrollscan.com","SCROLL_RPC_URL","SCROLL_RPC_URLS","https://scroll-rpc.publicnode.com"),
    81457: ChainSpec(81457,"blast","evm","ETH","0x4300000000000000000000000000000000000004",18,"https://blastscan.io","BLAST_RPC_URL","BLAST_RPC_URLS","https://blast-rpc.publicnode.com"),
    5000: ChainSpec(5000,"mantle","evm","MNT","0x201EBa5CC46D216Ce6DC03F6a759e8E766e956aE",18,"https://mantlescan.xyz","MANTLE_RPC_URL","MANTLE_RPC_URLS","https://rpc.mantle.xyz"),
}

ALL_SPECS = EVM_CHAINS


def get_spec(chain_id: int) -> ChainSpec:
    return EVM_CHAINS[int(chain_id)]


def rpc_urls(spec: ChainSpec) -> list[str]:
    primary = os.getenv(spec.rpc_env, "").strip()
    fallbacks = [x.strip() for x in os.getenv(spec.rpc_fallback_env, "").split(",") if x.strip()]
    # Never carry the known-bad Llama endpoint into the live Base quote path,
    # even if it remains in an older DEX_RPC_URLS environment value.
    blocked = {"https://base.llamarpc.com"}
    urls: list[str] = []
    for url in [primary, *fallbacks]:
        if url and url not in blocked and url not in urls:
            urls.append(url)

    from src.dragon.rpc_providers import load_providers, private_urls
    private = [u for u in private_urls(spec.chain_id, load_providers()) if u not in blocked]

    # Authenticated providers are preferred before public fallbacks. An explicit
    # DEX_RPC_URL remains first because it is an intentional operator pin.
    if spec.chain_id == 8453:
        explicit = list(urls)
        urls = []
        if primary and primary not in blocked:
            urls.append(primary)
        for url in private:
            if url not in urls:
                urls.append(url)
        for url in explicit:
            if url not in urls:
                urls.append(url)
        if os.getenv("DEX_RPC_AUTO_FALLBACK", "false").strip().lower() in {"1","true","yes","on"}:
            for url in ("https://mainnet.base.org","https://base-rpc.publicnode.com","https://1rpc.io/base"):
                if url not in urls:
                    urls.append(url)
        elif not urls:
            for url in ("https://base-rpc.publicnode.com","https://1rpc.io/base"):
                if url not in urls:
                    urls.append(url)
        return urls

    if urls:
        return urls
    for url in private:
        if url not in urls:
            urls.append(url)
    if not urls and spec.default_rpc:
        urls.append(spec.default_rpc)
    return urls


def env_chain_ids() -> list[int]:
    raw = os.getenv("DEX_CHAINS", "8453").strip()
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            cid = int(part)
        except ValueError:
            continue
        if cid in ALL_SPECS and cid not in ids:
            ids.append(cid)
    return ids or [8453]
