# Dragon — Base 8453 Two-Leg DEX Arbitrage Repair Core

Dragon is being rebuilt as a **Base-only (chain 8453), direct two-leg arbitrage scanner**.

## Hard perimeter

- Chain: **Base 8453 only**
- DEXs: **Aerodrome + Uniswap V3 only**
- Routes:
  - Aerodrome → Uniswap V3
  - Uniswap V3 → Aerodrome
- Triangular/cyclic routes: **disabled**
- Same-venue routes: **disabled**
- Live quote path: required before an opportunity is actionable
- Scanner has **no wallet, private key, signing, or transaction broadcast**
- Minimum net-profit floor: **$0.005**
- Search loop: continuous/event-driven; no mandatory 30-second scan cycle

Aerodrome's official documentation describes Aerodrome as a Base DEX with on-chain AMM liquidity, which is why the repair keeps the venue inside the Base execution perimeter. citeturn0search0turn0search1

## Core modules

```text
src/dragon/
  config.py       Base/venue hard-locks and runtime configuration
  rpc.py          bounded RPC pool, timeout, failover and cooldown
  models.py       raw-unit quote/opportunity models
  routes.py       exact two-leg route enforcement
  calculator.py   net-profit and flash-loan fee calculations
  scanner.py      pure opportunity evaluation; no execution
```

## Calculation path

```text
input
 → live quote leg 1
 → live quote leg 2
 → gas
 → flash-loan fee
 → safety buffer
 → NET
 → report only when NET >= $0.005
```

All on-chain amounts must remain integer/raw-unit values until an explicit decimal conversion is applied using token metadata. The scanner must not assume that every token has 12 decimals.

## RPC behavior

The RPC pool:
- races/chooses healthy endpoints by observed latency,
- applies per-call timeouts,
- cools down failed endpoints,
- fails over automatically,
- bounds concurrent calls,
- prevents one dead endpoint from blocking the whole scanner.

## Execution boundary

The repair core is intentionally **read-only**. Atomic execution remains a separate component. No live-money transaction signing is enabled by this core.

## Current status

Phase 1 is the perimeter/core repair. The next integration step is to wire **verified live Aerodrome and Uniswap V3 Base quote adapters**, then add dynamic sizing and an atomic execution hand-off.

```bash
pytest -q
```
