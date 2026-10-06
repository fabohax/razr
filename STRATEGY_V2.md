# Research strategy v2: confirmed multi-timeframe MACD entries

Date: 2026-10-05 (America/Lima). This is an original Python adaptation of
published indicator rules, not a copied profitable system or a production change.
No minimum daily trade count; at most four entries per UTC day. Long only.

## Internet research and limits of the evidence

- [Alexander Elder's own site](https://www.elder.com/product-page/elder-disk-2-1-for-ninja-trader-8-v2-1)
  documents his Triple Screen and Impulse tools. We borrow the separation of
  trend context from entry timing, not his original weekly/daily trading system.
- [Alex Spiroglou's MACD-V research, published by NAAIM (2022)](https://www.naaim.org/wp-content/uploads/2022/05/MACD-V-Alex-Spiroglou-WEB.pdf)
  defines MACD-V as MACD / ATR26 × 100, discusses crossover whipsaws, and gives
  an illustrative DAX strategy after costs. Its periods, market and holding times
  differ from BTC minute trading. We use its 50–150 momentum band as a testable
  filter; it does not establish profitability here. The paper also describes
  Elder impulse: rising EMA13 and rising MACD histogram mean positive impulse.
- [MACD MTF Strategy by JoseMetal](https://www.tradingview.com/script/GxAhH0i3/)
  documents agreeing higher/lower MACDs and ATR or wick-based stops. It recommends
  8h/12h with daily context. Its source is protected, so we do not copy its code
  or represent this implementation as equivalent. Its author's performance claim
  is not verified evidence for our market or parameters.
- [Deprez & Frommel, 2024](https://www.sciencedirect.com/science/article/pii/S1059056024003010)
  report favorable out-of-sample risk/return for selected portfolios of BTC trading
  rules after costs and multiple-testing controls. This supports careful evaluation
  of rule families, not guaranteed transfer to a 17-minute, 100x perpetual strategy.

No inspected source demonstrates that these exact BTC scalping rules are
profitable at the user's fees. Adaptation and independent testing are required.

## Why the example BUY should be filtered

The supplied screenshots show a small 1m momentum recovery during a broader
5m/15m decline. A mathematically valid bullish MACD crossover can reflect slowing
selling rather than a reversal. Positive 1m histogram does not require a positive
MACD line. Treat the cross as a setup, not an actionable trade by itself.
Screenshots include forming candles and do not identify the origin of B/S labels;
use confirmed data rather than asserting the labels prove a particular algorithm.

## Frozen rules before running the new experiment

Two entry families: `impulse` and `macdv` (the latter adds an hourly strength band).
Both use confirmed 1m bars and complete UTC-aligned higher bars only:

1. 1h: EMA13 rising, MACD histogram rising, MACD line positive, close above a
   rising EMA50. `macdv` also requires 50 <= MACD / Wilder ATR26 × 100 <= 150.
2. 15m: EMA13 and MACD histogram rising, histogram positive, close above EMA20,
   EMA20 above EMA50. This rejects long entries while intermediate impulse falls.
3. 5m: positive/rising histogram, rising EMA13, close above EMA20, and at least
   one low touched EMA20 within the last six complete 5m bars (pullback recovery).
4. 1m: wait for the second consecutive positive histogram close after the bullish
   crossover. That candle must close above the crossover candle's high and EMA20,
   with volume at least the previous 20 candles' average. Enter no earlier than
   the next open. A cross that immediately disappears never triggers an entry.
5. Default 60-minute cooldown from fill; no overlap; zero trades is acceptable.

The exact entry trigger requires the confirmation immediately after the cross;
we do not search future bars indefinitely or relocate the signal retrospectively.
The 5m low window is a backward-looking minimum, not a future-confirmed pivot.

## Structural SL and target after costs

Freeze the last three complete 5m bars' lowest low and Wilder ATR14 on 5m at the
signal close. SL = the lower of:

- that low minus 0.1 × ATR5m;
- signal close minus `atr_multiple` × ATR5m.

Test ATR multipliers **1.0 and 1.5**. Recalculate distance from the eventual
entry price but keep the signal-time stop price. Reject if outside **0.10–0.35%**;
never squeeze the stop inside structure to make an entry fit. These bounds are
research choices, not validated liquidation buffers.

TP is solved using entry taker fee, TP maker/taker fee, and the modeled SL taker
execution including slippage, to provide a **net** reward/risk of **1.0 or 1.5**.
The formula explicitly uses different exit notional for fees. Gross target has a
**0.30% floor and 0.80% ceiling**; reject infeasible entries. These replace the
original fixed 0.14% target, as authorized by the request to refine SL/TP.

Example before entry slippage: a 0.20% price stop, 1bp stop slippage, 5bp entry,
5bp stop exit, and 2bp maker TP imply about a **0.38% target for 1:1 net** or
**0.535% for 1.5:1 net**. Holding time remains capped at **17 minutes**. Larger
net targets may be incompatible with that deadline; time exits remain in results.

## Evaluation declared before results

Eight variants = two entry families × two ATR multipliers × two net reward/risk
settings. No MACD period optimization. Account sizing and execution assumptions
match v1: $1,000 starting equity, 1% margin at 100x, 2bp maker/5bp taker fees,
1bp adverse slippage on each taker fill, conservative unknown intrabar ordering.
Funding, liquidation and limit-order queues remain unmodeled.

Additional real OKX data: March 20–June 19 inclusive UTC, with warm-up before
April 1. Development April 1–May 15; validation May 16–May 31; final check June
1–June 19. Select from development only by mean net notional return, requiring
at least 15 development trades for a supported choice. If none qualifies, show
the best available variant only as an insufficient-sample diagnostic. Do not
change the selection after seeing validation or final results.

These intervals were not evaluated in the previous experiment, but precede
already-observed July–October data. Therefore this is additional retrospective
validation, not a clean forward test of a strategy invented before all data.
Existing July–October may be replayed only as reused-data diagnostics, not a new
untouched holdout. Sensitivity checks use 2bp slippage, one-minute extra entry
delay, and taker TP fees without reselecting a strategy.

Technical verification must cover closed-timeframe joins, future-data invariance,
second-close confirmation, exact net reward/risk after fees, structural stop gap
rejection, time-stop precedence, and backward-compatible v1 simulation.

## Follow-up exploration: impulse as a veto, not universal green alignment

The first strict experiment returned one development trade (four signal entries
rejected by structural stop bounds), zero validation trades, and zero final-check
trades. It is too sparse to estimate profitability. Preserve its full report as
`reports/strategy-v2-market-20261005.json`; do not call its one win an edge.

Before the follow-up comparison, define one simpler family, `censored`, with the
same four ATR/net-RR combinations and all entry, stop, target and timing rules
unchanged. Use the impulse filter as a veto:

- 1h: close above rising EMA50; exclude red impulse (EMA13 and histogram both
  falling). Neutral impulse is allowed; a positive MACD line is not required.
- 15m: exclude red impulse; close above EMA50 and EMA20 above EMA50. This permits
  an intermediate pullback to stabilize before its histogram turns positive.
- 5m: histogram rising, close back above EMA20 after a touch within six bars.
  Do not also require a positive histogram or rising EMA13 here.
- 1m: the same second-close confirmation, price breakout and volume test.

[StockCharts' own Impulse implementation documentation](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/elder-impulse-system)
explains the EMA13/histogram slopes and use of longer-term context. Our timeframe
mapping, stop/target bounds and confirmations remain an independent adaptation.
This follows the purpose of censorship—blocking opposing impulse—rather than
requiring every timeframe to reach the same momentum state simultaneously.

This is an **additional exploratory experiment after observing the strict
experiment**. Its validation and final-check dates are no longer untouched,
including the zero-trade information from the first run. Keep that limitation in
the report and require a future paper test for any apparent positive result. The
July–October replay also remains a reused-data diagnostic.

## MACD zero-line filter (2026-10-05)

Ignore entry crosses when MACD > 0 at the cross candle close. MACD <= 0
remains eligible. In v2, apply this to the cross candle, before the second-close
confirmation. Historical reports predate this filter and have not been rerun.

## Fixed TP update (2026-10-05)

Current TP replaces the net-RR target above: actual purchase price × 1.0016,
exactly +0.16% gross, before fees. Structural SL is unchanged. The planner uses
Parameters.tp_pct (default 0.16); legacy Rules.net_rr/min_tp_pct/max_tp_pct no
longer set the target. The runner no longer sweeps net RR. Earlier reports and
cost examples describe the previous target and have not been recalculated.

## Fixed stop update (2026-10-05)

Current SL = actual purchase fill × 0.9973 (−0.27% gross price move).
TP remains actual purchase fill × 1.0016 (+0.16%). Parameters.sl_pct sets
this stop in v1/v2; v2's earlier structural/ATR stop and distance rejection are
superseded. The v2 runner no longer sweeps ATR multipliers. Historical reports
and cost examples predate these fixed levels and have not been recalculated.
