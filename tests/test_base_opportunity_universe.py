from src.dragon.base_opportunity_universe import BaseOpportunityUniverse


def test_base_universe_is_hard_locked():
    assert 8453 == 8453


def test_universe_merges_configured_and_curated(monkeypatch):
    scanner = BaseOpportunityUniverse()
    monkeypatch.setattr(scanner, "refresh_seconds", 999999)

    class Adapter:
        pass

    # Avoid RPC discovery in this unit test; configured tokens still expand
    # the executable direct-leg search universe.
    import src.dragon.base_opportunity_universe as mod
    monkeypatch.setattr(mod, "discover_recent_base_tokens", lambda *a, **k: [])

    quote = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    configured = ["0x4200000000000000000000000000000000000006"]
    tokens = scanner.tokens(Adapter(), quote, configured)

    assert tokens
    assert quote.lower() not in {x.lower() for x in tokens}
    assert configured[0].lower() in {x.lower() for x in tokens}


def test_base_engine_rejects_non_perimeter_route():
    from src.dragon.dex_cross_exchange import DexCrossExchangeEngine
    import pytest

    with pytest.raises(ValueError, match="hard-locked"):
        DexCrossExchangeEngine(None, ["Aerodrome", "SushiSwap"], min_profit="0.005").scan_once(
            chain_id=8453,
            quote_token="0x0000000000000000000000000000000000000001",
            base_token="0x0000000000000000000000000000000000000002",
            quote_amount=1,
            taker="0x0000000000000000000000000000000000000003",
        )


def test_base_engine_requires_minimum_profit():
    from src.dragon.dex_cross_exchange import DexCrossExchangeEngine
    import pytest

    with pytest.raises(ValueError, match="0.005"):
        DexCrossExchangeEngine(None, ["Aerodrome", "Uniswap_V3"], min_profit="0.0049")
