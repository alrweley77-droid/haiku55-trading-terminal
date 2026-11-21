# HAIKU55 V2 release readiness (PAPER only)

## Verified in CI
- Python compilation and offline unit tests
- Isolated SQLite V2 balance starts at 10,000 USD (simulated)
- Legacy broker entry bypass rejected
- Atomic entry checks fresh market quotes, portfolio exposure, daily loss and duplicate symbols
- Dry-run supervisor and explicit PAPER execution environment gate
- Deterministic 25-cycle persistence/duplicate-entry regression

## Not yet verified
- Binance public USD-M endpoints from the intended Railway region: previous
  environment returned HTTP 451. Do not substitute fabricated quotes.
- Long-running Railway V2 process and restart/recovery under its own persistent volume.
- Forward-test of actual closed-candle signal behavior, funding, liquidation,
  exchange symbol precision, rate limits and partial network failures.
- Strategy performance on out-of-sample data. No profitability guarantee.
- Daily loss accounting across UTC day boundaries and restarts.
- Portfolio unrealized PnL under stressed spreads and fast gaps.

## Release gate
Do not mark PR ready or merge into a deployed branch while the above
integration and risk-model gaps remain. Existing Railway PAPER services and
historical account databases must remain untouched.

## Safe offline smoke command
```sh
python -m compileall -q app tests
python -m unittest discover -s tests -v
```

The CLI `python -m app.v2_runner --limit 40` only plans opportunities
and may fail if Binance blocks the hosting location. It never submits orders.

The optional V2 supervisor executes PAPER orders only when both
`--execute-paper` and `HAIKU55_V2_PAPER_EXECUTE=YES` are present.
Do not run this on an existing production database or service.
