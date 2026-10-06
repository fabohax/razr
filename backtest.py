"""Offline, long-only BTC-USDT-SWAP MACD candidate backtester."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

import pandas as pd

from indicators import compute_macd
from market_data import DataError, normalize_ohlcv
from replay import load_rows, parse_utc
from signals import utc, warmup

MINUTE = 60_000


@dataclass(frozen=True)
class Parameters:
    fast: int = 12
    slow: int = 26
    signal: int = 9
    tp_pct: float = .16
    sl_pct: float = .27
    time_stop_minutes: int = 17
    cooldown_minutes: int = 60
    daily_cap: int = 4
    maker_bps: float = 2.
    taker_bps: float = 5.
    slippage_bps: float = 1.
    tp_maker: bool = True
    setup_filter: bool = True
    delay_minutes: int = 0
    leverage: float = 100.
    margin_fraction: float = .01
    initial_equity: float = 1000.

    def validate(self):
        for name in ('fast', 'slow', 'signal', 'time_stop_minutes', 'daily_cap'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('cooldown_minutes', 'delay_minutes'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if self.fast >= self.slow:
            raise ValueError('fast must be less than slow')
        for name in ('tp_pct', 'sl_pct', 'leverage', 'margin_fraction', 'initial_equity'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if max(self.tp_pct, self.sl_pct) >= 100 or self.margin_fraction > 1:
            raise ValueError('price distances must be below 100%; margin fraction at most 1')
        for name in ('maker_bps', 'taker_bps', 'slippage_bps'):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value < 10000:
                raise ValueError(f'{name} must be finite in [0, 10000)')


def prepare(rows, p):
    """Each row is a decision at its close; higher bars join by closing time."""
    p.validate()
    df = normalize_ohlcv(rows)
    if df.empty or any(df.timestamp.diff().dropna() != MINUTE):
        raise DataError('input must contain consecutive one-minute candles')
    df = compute_macd(df, p.fast, p.slow, p.signal)
    df['decision_ms'] = df.timestamp + MINUTE
    df['trigger'] = df.eligible & (df.MACD_Hist.shift(1) <= 0) & (df.MACD_Hist > 0) & (df.MACD <= 0)
    source = df.copy()
    for minutes in (5, 15, 60):
        # Count rejects incomplete edge buckets; continuity above rejects inner gaps.
        bars = source.resample(f'{minutes}min', origin='epoch', label='left', closed='left').agg(
            open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
            close=('close', 'last'), volume=('volume', 'sum'), count=('close', 'count'))
        bars = bars[bars['count'] == minutes].copy()
        bars = compute_macd(bars, p.fast, p.slow, p.signal)
        ema_span = 50 if minutes == 60 else 20
        ema = bars.close.ewm(span=ema_span, adjust=False).mean()
        ready = pd.Series(range(len(bars)), index=bars.index) >= max(
            warmup(p.fast, p.slow, p.signal), 5 * ema_span)
        if minutes == 60:
            passed = (bars.close > ema) & (ema > ema.shift(1))
        elif minutes == 15:
            passed = (bars.MACD_Hist > 0) & (bars.close > ema)
        else:
            # Explicit setup: previous histogram <= 0, now rising, above EMA20.
            passed = (bars.MACD_Hist.shift(1) <= 0) & (bars.MACD_Hist > bars.MACD_Hist.shift(1)) & (bars.close > ema)
        key = f'filter_{minutes}m'
        context = pd.DataFrame({'decision_ms': bars.index.as_unit('ns').astype('int64') // 1_000_000 + minutes * MINUTE,
                                key: (ready & passed).values,
                                f'ready_{minutes}m': ready.values})
        df = pd.merge_asof(df.reset_index(drop=True), context, on='decision_ms', direction='backward')
    for key in [c for c in df if c.startswith(('filter_', 'ready_'))]:
        df[key] = df[key].eq(True)
    df['ready'] = df.eligible & df.ready_60m & df.ready_15m & df.ready_5m
    df['candidate'] = df.trigger & df.ready & df.filter_60m & df.filter_15m
    if p.setup_filter:
        df['candidate'] &= df.filter_5m
    return df


def simulate(df, start_ms, p, entry_plan=None):
    """Optional entry_plan(entry, frozen_signal_row, parameters) supplies SL/TP.

    The planner may use signal-time data and the eventual entry price, but no
    entry-bar high/low/close. Returning None rejects an incompatible entry.
    """
    p.validate()
    starts = df.index[df.timestamp == start_ms].tolist()
    if not starts or not bool(df.loc[starts[0], 'ready']):
        raise ValueError('evaluation start must match a candle after all timeframe warm-ups (about 251 hours)')
    first = starts[0]
    if len(df) - first < 2:
        raise ValueError('evaluation requires at least two candles')
    equity = peak = p.initial_equity
    drawdown = 0.
    position = None
    pending = None
    next_entry = 0
    trades = []
    daily = {}
    ambiguous = signals = unfilled = rejected_entries = 0
    slip = p.slippage_bps / 10000
    for i, row in enumerate(df.iloc[first:].itertuples(index=False), start=first):
        ts = int(row.timestamp)
        day = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
        daily.setdefault(day, 0)
        if pending is not None and i == pending['fill_index']:
            entry = float(row.open) * (1 + slip)
            plan = entry_plan(entry, pending['signal_row'], p) if entry_plan else dict(
                sl=entry * (1 - p.sl_pct / 100), tp=entry * (1 + p.tp_pct / 100))
            if plan is not None:
                if not all(math.isfinite(plan[k]) for k in ('sl', 'tp')) or not 0 < plan['sl'] < entry < plan['tp']:
                    raise ValueError('entry plan must provide finite positive SL < entry < TP')
                notional = equity * p.margin_fraction * p.leverage
                position = dict(signal_ms=pending['signal_ms'], entry_ms=ts, entry_price=entry,
                            units=notional / entry, entry_notional=notional,
                            entry_fee=notional * p.taker_bps / 10000,
                            **plan)
                daily[day] += 1
                next_entry = ts + p.cooldown_minutes * MINUTE
            else:
                rejected_entries += 1
            pending = None
        if position is not None:
            pos = position
            reason = None
            uncertain = False
            both = row.low <= pos['sl'] and row.high >= pos['tp']
            if ts >= pos['entry_ms'] + p.time_stop_minutes * MINUTE:
                reason, price = 'TIME', float(row.open) * (1 - slip)
            elif row.open <= pos['sl']:
                reason, price = 'SL', float(row.open) * (1 - slip)
            elif row.open > pos['tp'] or (not p.tp_maker and row.open == pos['tp']):
                reason, price = 'TP', pos['tp'] if p.tp_maker else float(row.open) * (1 - slip)
            elif row.low <= pos['sl']:
                reason, price = 'SL', pos['sl'] * (1 - slip)
                ambiguous += int(both)
                uncertain = bool(both)
            elif row.high >= pos['tp']:
                # Maker TP requires trading through the limit; touching alone is no fill.
                if not p.tp_maker or row.high > pos['tp']:
                    reason, price = 'TP', pos['tp'] * (1 if p.tp_maker else 1 - slip)
            if reason:
                exit_fee = pos['units'] * price * (p.maker_bps if reason == 'TP' and p.tp_maker else p.taker_bps) / 10000
                pnl = pos['units'] * (price - pos['entry_price']) - pos['entry_fee'] - exit_fee
                equity += pnl
                trades.append(dict(pos, exit_bar_ms=ts, exit_time_precision='bar; intrabar sequence unknown' if reason != 'TIME' else 'bar open',
                                   exit_price=price, exit_fee=exit_fee, reason=reason, pnl=pnl,
                                   net_notional_return_pct=pnl / pos['entry_notional'] * 100,
                                   ambiguous=uncertain))
                position = None
        marked = equity
        if position:
            marked += position['units'] * (float(row.close) - position['entry_price']) - position['entry_fee']
        peak = max(peak, marked)
        drawdown = max(drawdown, (peak - marked) / peak)
        if marked <= 0:
            raise ValueError('modeled equity exhausted; reduce margin fraction/leverage')
        if bool(row.candidate):
            signals += 1
            if position is None and pending is None and ts + MINUTE >= next_entry:
                fill_index = i + 1 + p.delay_minutes
                if fill_index < len(df):
                    fill_ts = int(df.timestamp.iloc[fill_index])
                    fill_day = pd.Timestamp(fill_ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
                    if daily.get(fill_day, 0) < p.daily_cap:
                        pending = dict(fill_index=fill_index, signal_ms=ts + MINUTE, signal_row=row)
                else:
                    unfilled += 1
    if pending:
        unfilled += 1
    gains = sum(max(t['pnl'], 0) for t in trades)
    losses = -sum(min(t['pnl'], 0) for t in trades)
    return dict(completed_trades=len(trades), qualifying_signals=signals, unfilled_end_signals=unfilled,
                rejected_entries=rejected_entries,
                win_rate_pct=100 * sum(t['pnl'] > 0 for t in trades) / len(trades) if trades else None,
                profit_factor=gains / losses if losses else None,
                net_expectancy=sum(t['pnl'] for t in trades) / len(trades) if trades else None,
                final_marked_equity=marked, return_pct=(marked / p.initial_equity - 1) * 100,
                max_drawdown_pct=drawdown * 100, ambiguous_trades=ambiguous,
                exits={reason: sum(t['reason'] == reason for t in trades) for reason in ('TP', 'SL', 'TIME')},
                entries_by_utc_day=daily, mean_entries_per_observed_day=sum(daily.values()) / len(daily),
                zero_entry_days=sum(v == 0 for v in daily.values()),
                evaluation_start_utc=utc(start_ms), evaluation_end_utc=utc(int(df.timestamp.iloc[-1]) + MINUTE),
                open_position=position, trades=trades)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evaluation-start', required=True, help='timezone-aware first evaluation candle; preceding data warms indicators')
    parser.add_argument('--data-kind', choices=('historical', 'synthetic'), required=True)
    parser.add_argument('--compare-stops', action='store_true', help='development comparison of 0.07, 0.10, 0.14 percent stops')
    parser.add_argument('--no-setup-filter', action='store_true')
    parser.add_argument('--tp-taker', action='store_true')
    for name in ('fast', 'slow', 'signal', 'time_stop_minutes', 'cooldown_minutes', 'daily_cap', 'delay_minutes'):
        parser.add_argument('--' + name.replace('_', '-'), type=int, default=getattr(Parameters(), name))
    for name in ('tp_pct', 'sl_pct', 'maker_bps', 'taker_bps', 'slippage_bps', 'leverage', 'margin_fraction', 'initial_equity'):
        parser.add_argument('--' + name.replace('_', '-'), type=float, default=getattr(Parameters(), name))
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError('output must differ from input')
        p = Parameters(**{k: getattr(args, k) for k in asdict(Parameters()) if k not in ('tp_maker', 'setup_filter')},
                       tp_maker=not args.tp_taker, setup_filter=not args.no_setup_filter)
        source = args.input.read_bytes()
        rows = load_rows(args.input, source)
        df = prepare(rows, p)
        start = parse_utc(args.evaluation_start)
        stops = (.07, .10, .14) if args.compare_stops else (p.sl_pct,)
        from dataclasses import replace
        report = dict(format_version=1, strategy='mtf-macd-long-v1', market='OKX BTC-USDT-SWAP',
                      data_kind=args.data_kind, provenance='caller supplied; contract identity not independently verified',
                      source_sha256=hashlib.sha256(source).hexdigest(), candles=len(df),
                      assumptions=['all file bars asserted closed; no network access',
                                   'closed UTC-aligned higher bars only; next-open taker entry',
                                   '5m setup: previous histogram nonpositive, rising histogram, close above EMA20',
                                   'maker TP trades through limit; no queue/liquidity model',
                                   'SL before TP when intrabar sequence unknown; gap stops at open',
                                   'time stop at entry+17m by default; exit before that bar intrabar tests',
                                   'slippage applied to taker fills; funding and liquidation NOT modeled',
                                   '100x scales notional; margin_fraction controls account exposure',
                                   'drawdown uses bar-close marked equity; open position not forcibly closed',
                                   'UTC daily counts include partial days; no minimum daily entries',
                                   'stop comparison is exploratory; reserve untouched data for final evaluation'],
                      runs=[dict(parameters=asdict(replace(p, sl_pct=s)), results=simulate(df, start, replace(p, sl_pct=s))) for s in stops])
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        for run in report['runs']:
            r = run['results']
            print(f"SL {run['parameters']['sl_pct']}%: {r['completed_trades']} trades, return {r['return_pct']:.3f}%, drawdown {r['max_drawdown_pct']:.3f}%")
        print(f'Report: {args.output}')
        return 0
    except (ValueError, OSError, DataError) as exc:
        print(f'Backtest error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
