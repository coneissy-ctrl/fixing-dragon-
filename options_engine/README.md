# Options Engine — Demo/Paper First

This module is isolated from Dragon's DEX arbitrage engine and provides a common strategy/risk/execution foundation for Binance Options and Deriv Options.

## Safety state
- Default mode: `paper`
- `OPTIONS_DRY_RUN=true`
- Live execution is hard-locked in this initial build.
- No withdrawal functionality.
- No secrets committed to Git.

## Verification
```bash
python -m unittest discover -s options_engine/tests -v
```

## Promotion gate
Real-money execution requires separate live adapters and explicit promotion only after unit, paper, demo, reconciliation, reconnect/stale-data and risk-limit verification. Deriv's current Options API uses REST for account/OTP setup and an authenticated demo WebSocket for trading; public WebSocket is available for unauthenticated market data.
