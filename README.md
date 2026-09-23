# Dragon — Base two-leg DEX arbitrage scanner

## Perimeter
- Chain: Base (8453) only.
- Venues: Aerodrome, Uniswap V3, SushiSwap.
- Routes: direct two-leg only.
- No triangular routes.
- No cyclic routes.
- No cross-chain routes.
- No wallet, signing, or transaction broadcast in the scanner.
- Minimum net profit filter: $0.005.
- Continuous/event-driven scanning; no mandatory 30-second cycle.

## Isolation rule
Every venue scanner/adapter is an independent failure domain:
- one venue's RPC, quote, ABI, or adapter error must not stop another venue;
- venue failures are recorded and isolated;
- the opportunity engine consumes only successful live quotes;
- no venue may call another venue's adapter directly;
- shared RPC infrastructure is bounded and failover-capable, but quote/adapter state remains venue-scoped.

## Search model
Each venue can independently produce live quotes. The opportunity engine combines successful quotes into exactly six directed two-leg permutations:
1. Aerodrome → Uniswap V3
2. Uniswap V3 → Aerodrome
3. Aerodrome → SushiSwap
4. SushiSwap → Aerodrome
5. Uniswap V3 → SushiSwap
6. SushiSwap → Uniswap V3

The engine continuously evaluates both directions for executable token pairs and rejects routes below the net-profit floor after configured costs.

## Calculation path
input → leg 1 live quote → leg 2 live quote → swap costs → gas → flash-loan fee → safety buffer → NET

## Execution boundary
The scanner remains read-only. Atomic execution/signing is outside this workspace boundary until the live quote path and execution hand-off are independently verified.

## Isolated analysis scanners
The control plane also uses independent scanners for separate concerns:
- Liquidity: executable liquidity check.
- Price impact: size-dependent price-impact check.
- Gas: current execution-cost input validation.
- Staleness: quote freshness check.
- Execution: route/execution readiness check.
- Profit: hard net-profit floor check.
- Simulation: full two-leg simulation gate.
- Sizing: executable amount validation.

Each scanner has its own failure boundary. A failed analysis scanner returns a failed result rather than terminating the other scanners. These scanners do not bypass the Base-only perimeter, the isolated venue adapters, the direct two-leg route restriction, or the external execution boundary.
