# HAIKU55 operational and financial safety

## Current execution boundaries

- Exchange access is limited to read-only public Binance USDⓈ-M Futures market-data endpoints for BTCUSDT, ETHUSDT and SOLUSDT.
- NO exchange API keys, seed phrases, private keys, wallets, signatures or real-order APIs are used.
- All positions, PnL, stops, targets, funding and liquidation events are PAPER-only SQLite records.
- Provider model outputs are parsed as data only; they cannot execute orders or override the deterministic risk gate.
- Four-model review is optional. When enabled but not configured or providers fail, the AI council abstains.

## Risk engine limitations

The software is a prototype for education/testing; it is NOT suitable for real-money unattended execution. It lacks exchange-order reconciliation, Binance-accurate liquidation accounting, symbol/tier maintenance-margin brackets, precision constraints, order-book depth, latency-sensitive slippage and actual fee-tier discovery.

Stops and targets are checked against periodically polled Binance mark prices, not exchange-side conditional orders. Simulated fills use assumed slippage. Funding uses the last published rate for one observed funding boundary; if the service misses multiple funding boundaries, earlier rates and payments cannot be reconstructed. The liquidation threshold uses an illustrative 0.5% maintenance-margin assumption and is NOT Binance tier-accurate. Margin and fee accounting are simplified PAPER estimates.

The UTC daily loss gate includes unrealized PnL (including estimated round-trip fees and funding) when deciding whether to allow new entries. It does not automatically liquidate existing paper positions at the daily loss threshold. Per-symbol cooldowns and sampled price history are in memory and reset on service restart.

On a KILL action the engine attempts to close paper positions at the last fresh observed mark and writes a persistent lock. If feed data is stale, positions remain unresolved rather than receiving fictional fills. There is no API action to reset the kill lock; deliberate offline maintenance/reset of the paper database is required.

## Web security and permissions

- POST actions require a long secret CONTROL_TOKEN in an Authorization Bearer header.
- If CONTROL_TOKEN is unset, all POST operations fail closed.
- GET /api/status and GET /api/trades are **not authenticated**. Anyone with access to the public hosting domain can see paper holdings and event history. Put the service behind upstream authentication or a private network if that is unsuitable.
- Set secrets only in the hosting provider's encrypted variable manager; never commit them or expose them in screenshots, browser URLs or public posts.
- Be alert to clipboard-sharing or browser extensions that could expose a token typed into the dashboard.
- Deploy one replica with a persistent volume mounted at /data. Multiple replicas may duplicate strategy decisions or corrupt the ledger.
- Read-only market feed failure marks prices STALE and blocks new paper orders. The dashboard must not silently substitute generated prices for market data.
- Model APIs can change or fail; validate provider permissions, billing and model identifiers before enabling AI_MODE.

## How to safely extend

For real exchange execution later, do not simply add wallet keys to this application. Use a segregated execution service, signed order authorization, reconciliation, explicit HUMAN approval of meaningful risk, risk limits including unrealized loss, a tested order lifecycle and separate secret-management architecture. Obtain operator approval and test thoroughly on testnet first.

Any published performance must clearly disclose whether results are simulated or real and must not imply guaranteed returns.
