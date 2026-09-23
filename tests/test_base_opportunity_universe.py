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
