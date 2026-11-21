# HAIKU55 V2 — Dynamic Futures PAPER redesign

Status: development specification, not deployed.

## User-approved goals
- Automatically discover liquid Binance USDⓈ-M perpetual contracts; no BTC/ETH/SOL-only hardcoding.
- Target 15–30 completed PAPER trades per UTC day as a performance objective, never a forced quota.
- Use **10,000 USD simulated starting balance** for a NEW, ISOLATED V2 test ledger.
- Keep existing Singapore PAPER ledger and US deployment unchanged.
- PAPER only; no real orders or API trading credentials.

## Architecture
1. Universe service: exchangeInfo + 24h ticker, filter TRADING perpetual USDⓈ-M, exclude unsuitable spreads, insufficient volume, and invalid market data; rank top 30–50; refresh periodically.
2. Market stream: websocket multiplexing with reconnect/backoff, heartbeats, freshness gate, bounded queues; REST fallback for bootstrap.
3. Signals: independent momentum, breakout and mean-reversion strategies with 1m/5m/15m context; fees and slippage incorporated; log accept/reject reasons.
4. Ranking: score candidate opportunities and prevent correlated overexposure and duplicate entries.
5. Risk/execution: separate paper execution and isolated account ledger; maximum concurrent positions, leverage/size caps, equity drawdown and daily loss stops, exchange tick/step precision, realistic funding and fees.
6. Dashboard: dynamic symbols, candidates, trade frequency, rejected signals, open/closed positions, equity and risk limits.

## Balance isolation requirements
- Do not overwrite existing account balance, positions, trade history or storage.
- V2 uses separate namespace/database or ledger with initial_cash_usd=10000.00, with unique run ID and explicit schema migration.
- Starting cash is not PnL or a deposit to any real exchange account.
- Avoid resetting balances on process restart; idempotent initialization.
- Do not expose controls for production live trading.

## Acceptance criteria before deployment
- Unit tests for universe filters, symbol changes, rate limits, reconnects, stale feed, risk gates, stop/target, ledger initialization.
- Backtests and paper-forward validation with fee/slippage and daily turnover statistics.
- Verify zero changes to existing US and Singapore services/volumes.
- No deployment, merge or activation without explicit follow-up approval.
