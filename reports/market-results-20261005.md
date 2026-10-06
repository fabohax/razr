# Real-market MACD backtest — 2026-10-05

**Result: reject the tested candidate for live use. All six development variants lost after costs, and the frozen least-loss variant failed on the holdout.**

## Data and split

- Source: public OKX `GET /api/v5/market/history-candles`, instrument `BTC-USDT-SWAP`, `bar=1m`.
- 154,080 consecutive minutes, 2026-06-20 00:00 UTC through 2026-10-05 00:00 UTC exclusive. Confirmed candles only; zero missing minutes.
- Warm-up: June 20–30. Development: July 1–August 31 (62 days). Holdout: September 1–October 4 (34 days). Dates are UTC.
- The six variants were declared before running the comparison. Select highest mean net return per trade as a percentage of entry notional; signal frequency is secondary. No holdout tuning.
- Dataset SHA-256: `056b51bc4a07b8e2ff268b77f8b989eb6c8722859c3ccfaaef86ea19441de140`.

## Development results

| 5m setup filter | SL | Trades | Net account return | Profitable trades | Profit factor | Entries/day |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| On | 0.07% | 73 | -7.53% | 21.9% | 0.125 | 1.18 |
| On | 0.10% | 73 | -7.93% | 24.7% | 0.133 | 1.18 |
| On | 0.14% | 73 | -8.15% | 26.0% | 0.135 | 1.18 |
| Off | 0.07% | 197 | -19.17% | 23.9% | 0.132 | 3.18 |
| Off | 0.10% | 197 | -19.93% | 26.9% | 0.141 | 3.18 |
| Off | 0.14% | 197 | -20.81% | 28.4% | 0.142 | 3.18 |

SL 0.07% with the 5m filter was the least-loss setting, not a profitable winner.

## Frozen holdout results

- Completed trades: 29; profitable trades: 13.8%; profit factor: 0.074.
- Net account return: -3.44%; final equity: $965.58 from $1,000.
- Candle-close marked maximum drawdown: 3.44%.
- Mean net return per trade: -0.1207% of entry notional.
- Exits: 4 TP, 18 SL, 7 time stops. No ambiguous TP/SL candles. No open terminal position.
- Frequency: 0.85 entries/day; 19 of 34 days had zero entries. Daily distribution: 0 entries on 19 days; 1 on 6; 2 on 6; 3 on 1; 4 on 2.
- Gross trade P&L after modeled slippage but before fees: −$7.08. Fees: $27.33. Net loss: $34.42. This sample lost before fees as well.

## Sensitivity on the same frozen setting

| Scenario | Net account return | Profitable trades | Profit factor |
| --- | ---: | ---: | ---: |
| 2bps_slippage | -4.26% | 10.3% | 0.046 |
| 1minute_entry_delay | -3.14% | 20.7% | 0.117 |
| taker_tp | -3.60% | 13.8% | 0.032 |

## Assumptions and limits

- Long only. MACD 12/26/9 on all timeframes. TP 0.14%; SL 0.07%; time stop 17 minutes; cooldown 60 minutes; maximum four entries per UTC day.
- Entry at next 1m open plus 1 bp slippage, taker fee 5 bps. TP is a resting maker limit charged 2 bps; SL/time exits are taker plus 1 bp slippage.
- Account sizing: 1% of current equity allocated as margin at 100x, so entry notional equals current account equity. Reported account returns are not returns from placing the entire account at 100x.
- Unknown intrabar ordering assumes SL first. Maker TP requires trading through its limit. Gap stops use executable opening prices. Minute bars cannot establish order queues, spread, precise intrabar order, or actual fills.
- Funding, liquidation, order-size rounding, and book depth are not modeled. Holdout has only 29 trades. This is historical evidence against this candidate in the tested periods, not a universal claim about MACD.
- Both periods failed; do not deploy the least-loss parameters as an established edge. Any revised strategy needs a new untouched evaluation period or forward paper test.

## Reproduce

```bash
.venv/bin/python fetch_history.py --start 2026-06-20T00:00:00Z \
  --end 2026-10-05T00:00:00Z --output data/okx-btc-usdt-swap-1m-20260620-20261005.json
.venv/bin/python run_market_backtest.py data/okx-btc-usdt-swap-1m-20260620-20261005.json \
  --development-start 2026-07-01T00:00:00Z --holdout-start 2026-09-01T00:00:00Z \
  --output reports/market-backtest-20261005.json
```

Downloader refuses to overwrite an existing dataset; use the saved file or choose a new path. All backtest parameters and full trade records are in the [JSON report](market-backtest-20261005.json). Holdout trades are also in [CSV](holdout-trades-20261005.csv).

Reference: [OKX history-candle documentation](https://app.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history).

Verification: 126 offline tests passed, including confirmed-candle/provenance checks, missing-minute rejection, future-data invariance, fee arithmetic, stops, time exits, and daily caps.
