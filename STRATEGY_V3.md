# Strategy v3: trend-aligned range breakout and relative volume

Research date: 2026-10-05, America/Lima. All earlier strategy parameters may
change by the user's latest instruction. Fees remain the user's confirmed account
rates. This experiment is an original implementation, not live-bot deployment.

## Rationale and sources

Price must actually escape a prior range rather than merely cross a smoothed
momentum line. Volume is a confirmation hypothesis that we compare against an
otherwise identical no-volume control.

- [Gerritsen et al., Bitcoin technical trading rules](https://www.sciencedirect.com/science/article/pii/S1544612319303770)
  report favorable forecasting/risk-adjusted results for some range-breakout rules
  using daily historical BTC data. This motivates testing the family; it does not
  establish an intraday perpetual edge.
- [TradingView's relative-volume definition](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/)
  divides current volume by a historical mean excluding the current bar. We adapt
  the window to 20 completed 5m bars and use OKX contract volume. Total candle
  volume is not aggressive-buy/sell delta or proof of institutional activity.
- [OKX liquidation FAQ](https://www.okx.com/en-gb/help/forced-liquidation-faq)
  explains why 100x can liquidate before a 1% adverse move. This experiment allows
  wider price stops and uses 10x as a margin assumption. Liquidation is still not
  modeled; leverage is not used to manufacture signal profitability.

## Frozen entry rules

1. Use actual BTC-USDT-SWAP 1m candles for execution and complete UTC-aligned
   5m/1h candles for signals/context. Warm EMA50 with 250 preceding hourly bars.
2. Hourly context: long only above a rising EMA50; short only below a falling
   EMA50. No MACD gate, no requirement that four correlated indicators agree.
3. 5m channel: highest high and lowest low of the **previous 20 bars**. Exclude
   the breakout candle from the channel and volume mean.
4. Long: close above upper channel plus 0.1 Wilder ATR14; previous close had not
   already escaped its own prior upper channel. Close in the top 25% of its
   candle. Short: symmetric lower-channel break and bottom 25% close.
5. Signal candle range cannot exceed 2.5 ATR14. Test relative volume >=1.5 or
   >=2.0; include threshold 0.0 as a no-volume control. Volume denominator is the
   previous 20 completed 5m bars' mean. This is simple rolling RVOL, not seasonal
   time-of-day adjusted RVOL.
6. Signal only at the 5m close; next 1m opening execution with adverse slippage.
   No propagation of a 5m signal across subsequent minutes. No overlapping
   positions, 30-minute entry cooldown, maximum four entries per UTC day.

## SL, TP, time and sizing

- Freeze the signal-time channel and ATR. Long SL is the lower of signal close
  minus 1.5 ATR and upper channel minus 0.1 ATR; short SL is symmetric.
- Reject an entry whose stop distance is outside 0.15–1.20% from its actual fill.
  Never move the stop inside the invalidation level to fit a desired ratio.
- Target 1.0 or 1.5 **net** reward/risk, after entry and outcome-specific exit fees
  and stop slippage. Gross TP floor 0.30%, ceiling 3.00%; reject infeasible trades.
- Compare time stops **60 and 120 minutes**. No trailing or break-even logic.
- Size notional to lose at most **0.25% of current account equity** at the modeled
  SL including fees/slippage. Cap notional at equity × 10x × 10% margin allocation
  (equity itself). A gap can exceed the planned loss.
- Maker TP 2bp; taker entry/SL/time/final exit 5bp. Baseline adverse slippage 1bp
  per taker fill. A maker limit must trade through its price; no queue model.
- Unknown intrabar ordering assumes SL first. Opening gaps and time exits use
  opening prices. Close any remaining position at the final candle close with
  taker costs, explicitly labeled END; do not hide final unrealized exposure.

## Evaluation declared before outcomes

Twelve combinations = RVOL {0,1.5,2} × net RR {1,1.5} × time {60,120}.
All other rules above remain fixed. Do not extend the grid after seeing losses.

Download November 20, 2025–March 20, 2026 exclusive UTC. Warm-up precedes December
1. Development: December 1–January 31 (62 days). Validation: February (28 days).
Final check: March 1–19 (19 days). These market intervals were not evaluated in
v1/v2. Select using development only, by highest mean realized net R (PnL divided
by planned fee-inclusive stop loss) among variants with >=30 completed development trades. If none qualifies,
label any selection an insufficient-sample diagnostic. Freeze selection to a JSON
file before validation and final evaluation; do not reselect from those outcomes.

The strategy was designed after observing later 2026 markets in prior work. Even
though these intervals are new to this evaluation, this is a retrospective study,
not an independent future paper test. State that limitation explicitly.

Run a matched final-period volume ablation for RVOL 0,1.5,2, retaining the selected
RR/time. Do not change the selection from that comparison. Stress the selected
setting with 2bp slippage, five-minute entry delay, taker TP, and a hypothetical
1bp funding charge at each UTC 00/08/16 settlement boundary for either side.
Funding stress is not reconstructed historical funding; baseline excludes funding.

Report side counts, costs, net notional expectancy, account return, drawdown,
profit factor, zero-trade days, exits, stop/target distributions and full trades.
Drawdown marks open positions at minute closes including estimated taker close
costs. Candle range volume is a directional proxy only. No book depth, contract
rounding, funding history, mark-price liquidation, or real maker queue is modeled.
