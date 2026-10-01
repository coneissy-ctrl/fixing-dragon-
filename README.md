# deriveonly

Deriv-only binary options engine for 1-minute and 5-minute monitoring.

## Runtime
- Entry point: `python -m options_engine.live_monitor`
- Live Deriv market-data WebSocket
- Deriv account authentication through configured credentials
- Live account balance endpoint: `/account/balance`
- Health/dashboard endpoint: `/health`
- OAuth endpoints are available when configured.
- Real-money execution remains explicitly gated by account mode and the live-trading flag.

## Strategy
The engine maintains independent 1m and 5m candle streams and deterministic CALL/PUT signals using EMA5/EMA12 trend alignment, candle direction, ATR(14), momentum and a confidence threshold. Martingale is disabled.

## Configuration
Copy `.env.options.example` to your secret environment configuration and keep credentials out of source control.

## Verification
```bash
python -m compileall -q options_engine
python -m unittest discover -s options_engine/tests -v
python -m options_engine.deriv_live_smoke
```
