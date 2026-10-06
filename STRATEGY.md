# Candidate MACD strategy for evaluation

Date: 2026-10-05. Status: candidate implemented in offline `backtest.py`;
not integrated into the live bot or validated for market performance.
Real-market v1 testing failed after costs; see
`reports/market-results-20261005.md`. The refined research strategy is documented
in `STRATEGY_V2.md`; neither version has established a profitable edge.

## Objective and assumptions

Read-only BTC perpetual long-entry alerts. The latest user requirement accepts
0–4 alerts per day without a minimum; cap entries at four per UTC day.
Keep MACD as the entry trigger. Target a 0.16% underlying-price gain and exit
after at most 17 minutes from the actual fill. User confirmed the underlying-price
target and BTC-USDT-SWAP contract. Use OKX BTC-USDT-SWAP (CCXT unified symbol
BTC/USDT:USDT), consistent with the existing OKX exchange configuration.
User confirmed account fees: maker 0.0200%, taker 0.0500% per fill.
100x is an execution assumption, not a signal-quality parameter.

Current production supports OKX BTC/USDT spot at 1m and emits both BUY and SELL
MACD crosses. It has no implemented TP, SL, time stop, or higher-timeframe filter.
The legacy replay simulation buys at the next open and exits on SELL; use the
separate `backtest.py` for this candidate. A spot feed is insufficient to validate
perpetual execution costs, basis, spread, funding, or liquidation behavior.

## Candidate rules to test

1. Use the intended perpetual's 1m OHLCV; derive complete UTC-aligned 5m, 15m,
   and 1h bars. A decision can use only bars closed by that decision time.
   Fetch enough prior history to warm every indicator, including hourly EMAs.
2. Hourly regime: close above EMA50 and EMA50 higher than its preceding value.
3. 15m confirmation: MACD(12,26,9) histogram positive and close above EMA20.
4. 5m setup: MACD histogram rising following a pullback, with close above EMA20.
   Test this filter as an optional addition rather than assuming it improves results.
5. 1m trigger: confirmed bullish MACD(12,26,9) cross. Test (8,21,5) separately.
   Emit only if all enabled filters pass. SELL is not a short-entry alert in this
   long-only candidate.
6. Define entry from the executable ask when the alert is received, not from an
   already closed candle. For candle backtests, use the next available open plus
   spread/slippage and model notification/manual-entry delay separately.
7. TP = entry × 1.0016. Test fixed SL distances of 0.07%, 0.10%, and 0.14%.
   Alternative: recent five closed 1m bars' low minus one tick; accept only when
   the resulting stop distance is within the tested bounds. Skip a setup if its
   structural stop is incompatible with the chosen maximum distance.
8. Exit at TP, SL, or entry + 17 minutes, whichever happens first. No overlapping
   candidate trades. Trial cooldown: 60 minutes from entry. Persist cooldown,
   daily count, and candidate lifecycle across restarts. Recovered stale crosses
   are audit events, not new actionable entries.
9. Live alerts show entry reference and expiry, TP/SL price and percentage,
   time deadline, timeframe confirmations, estimated costs, and strategy version.
   Since the bot does not place orders or know a manual fill, its hypothetical
   lifecycle must be labeled separately from an actual position's exits.

All filters and cooldown values above are hypotheses, not empirically selected
parameters. Evaluate a small predeclared set and keep the simplest robust variant.

## Historical cost-adjusted reward/risk (prior 0.14% TP)

Let T = 0.14%, S = stop distance, and C = approximate round-trip fees plus
spread/slippage expressed as a percentage of entry notional. Then:

- Net winning move ≈ T − C.
- Net losing move ≈ S + C.
- Net reward/risk ≈ (T − C) / (S + C).
- Binary TP/SL break-even win rate ≈ (S + C) / (T + S).

These are approximations: actual exit notional differs, execution costs can differ
between winners and losers, and time-stop exits have variable returns. Evaluate
those exits directly rather than treating them all as TP or SL outcomes.

| SL | Gross reward/risk | Break-even, C=0 | Net reward/risk, C=0.10% | Break-even, C=0.10% |
| --- | --- | --- | --- | --- |
| 0.07% | 2.00 | 33.33% | 0.235 | 80.95% |
| 0.10% | 1.40 | 41.67% | 0.200 | 83.33% |
| 0.14% | 1.00 | 50.00% | 0.167 | 85.71% |

OKX's published fee example uses 0.02% maker and 0.05% taker per fill:
https://www.okx.com/en-eu/help/how-to-calculate-the-contract-transaction-fee
User confirmed these account rates. Two taker fills imply
approximately C=0.10% before spread/slippage. A 0.07% SL then yields roughly
+4% margin on a TP and −17% on an SL at 100x, before other costs. At C=0.12%,
the same stop requires about 90.48% binary wins. If C >= T, the target offers no
positive net TP outcome under these assumptions. Maker entry cannot be assumed
filled; include non-fills and adverse selection in evaluation.

With the confirmed fees and a candidate 0.07% SL, approximate scenarios before
spread, slippage, funding, and exit-notional differences are:

| Entry / TP / SL execution | Net TP move | Net SL loss | Net reward/risk | Binary break-even win rate |
| --- | --- | --- | --- | --- |
| Taker / taker / taker | 0.04% | 0.17% | 0.235 | 80.95% |
| Taker / maker / taker | 0.07% | 0.17% | 0.412 | 70.83% |
| Maker / maker / taker | 0.10% | 0.14% | 0.714 | 58.33% |

For outcome-dependent costs, binary break-even is net loss divided by net gain
plus net loss. A resting TP may execute as maker, but order type alone does not
guarantee maker fees. Maker entry is a separate execution hypothesis requiring
non-fill and latency modeling. Time-stop exits should use their actual execution
fees and returns. No scenario establishes a profitable strategy without measured
win rates and execution outcomes.

## Evaluation required before selecting parameters

- Obtain preferably 6–12 months of actual target-contract data, with coverage of
  multiple volatility regimes. Include trade/order-book data where available;
  1m bars cannot establish fills at these narrow distances precisely.
- Split chronologically into development, validation, and untouched test periods;
  use walk-forward checks. Do not tune against the final test results.
- Compare raw MACD with successive regime/setup filters, the three SL distances,
  and the alternative MACD periods. Freeze a small search space in advance.
- Include realistic entry delay, fees, spread/slippage, funding when applicable,
  ticks, gaps, and mark-price liquidation rules for the chosen margin mode.
- If both TP and SL occur inside a candle with unknown sequence, assume SL first
  and disclose ambiguous-trade counts. Fill gaps at available prices, not guaranteed
  stop prices. Treat time stops at the first executable price at/after the deadline.
- Report net expectancy, profit factor, drawdown, trade count, win/loss/timeout
  rates, average holding time, alerts per day, zero-alert days, and uncertainty.
  Stress costs and latency; reject an edge that disappears with small changes.
- Optimize net expectancy and stability with desired signal frequency as a
  secondary constraint. Do not loosen filters merely to force one daily alert.
- Forward-test frozen rules with paper alerts before using them for live trades.

The best stop or filter combination is unknown until this evaluation is complete.
Public OKX history endpoint documentation:
https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history

## MACD zero-line filter (2026-10-05)

Ignore entry crosses when MACD > 0 at the cross candle close. MACD <= 0
remains eligible. In v2, apply this to the cross candle, before the second-close
confirmation. Historical reports predate this filter and have not been rerun.

## Fixed stop update (2026-10-05)

Current SL = actual purchase fill × 0.9973 (−0.27% gross price move).
TP remains actual purchase fill × 1.0016 (+0.16%). Parameters.sl_pct sets
this stop in v1/v2; v2's earlier structural/ATR stop and distance rejection are
superseded. The v2 runner no longer sweeps ATR multipliers. Historical reports
and cost examples predate these fixed levels and have not been recalculated.
