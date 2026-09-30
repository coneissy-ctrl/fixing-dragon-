# Options Engine — Binary 1m / 5m

Paper-first binary-options engine with isolated broker adapters.

## Modes
- **1m:** completed 1-minute candle -> 60-second CALL/PUT signal.
- **5m:** completed 5-minute candle -> 300-second CALL/PUT signal.
- Both use the same configured fixed stake.
- One signal maximum per completed candle/timeframe.
- 1m and 5m strategy state is independent.

## Signal filters
EMA5/EMA12 trend alignment, candle direction, ATR(14) volatility/body filter, price position versus EMA5, and a minimum confidence threshold. Weak/choppy candles are skipped.

## Risk
Martingale is permanently disabled. A loss never increases the next stake. Daily loss, consecutive-loss, maximum stake, and open-position limits remain enforced.

## Safety
Default mode is paper and live execution remains hard-locked. Demo adapters must pass connectivity, order lifecycle, stale-data, reconnect, reconciliation, and risk tests before any live adapter is considered.
