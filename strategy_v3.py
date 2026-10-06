"""Bidirectional range breakout with relative volume and risk-based sizing.

Research only. Rules and evaluation protocol: STRATEGY_V3.md.
"""
from dataclasses import dataclass
import math

import pandas as pd

from market_data import DataError, normalize_ohlcv
from strategy_v2 import atr

MINUTE = 60_000


@dataclass(frozen=True)
class Rules:
    channel_bars: int = 20
    volume_bars: int = 20
    min_rvol: float = 1.5
    atr_multiple: float = 1.5
    net_rr: float = 1.
    hold_minutes: int = 60
    cooldown_minutes: int = 30
    daily_cap: int = 4
    delay_minutes: int = 0
    min_sl_pct: float = .15
    max_sl_pct: float = 1.2
    min_tp_pct: float = .30
    max_tp_pct: float = 3.
    risk_pct: float = .25
    leverage: float = 10.
    max_margin_fraction: float = .10
    maker_bps: float = 2.
    taker_bps: float = 5.
    slippage_bps: float = 1.
    tp_maker: bool = True
    funding_stress_bps: float = 0.
    initial_equity: float = 1000.

    def validate(self):
        for name in ('channel_bars', 'volume_bars', 'hold_minutes', 'daily_cap'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('cooldown_minutes', 'delay_minutes'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        for name in ('atr_multiple', 'net_rr', 'min_sl_pct', 'max_sl_pct', 'min_tp_pct',
                     'max_tp_pct', 'risk_pct', 'leverage', 'max_margin_fraction', 'initial_equity'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        for name in ('min_rvol', 'maker_bps', 'taker_bps', 'slippage_bps', 'funding_stress_bps'):
            if not math.isfinite(getattr(self, name)) or not 0 <= getattr(self, name) < 10000:
                raise ValueError(f'{name} must be finite in [0, 10000)')
        if not self.min_sl_pct <= self.max_sl_pct < 100 or not self.min_tp_pct <= self.max_tp_pct < 100:
            raise ValueError('invalid price distance bounds')
        if self.risk_pct > 100 or self.max_margin_fraction > 1:
            raise ValueError('risk/margin allocation exceeds account equity')


def breakout_bars(bars, rules):
    """Breakout level and volume denominator exclude the signal candle."""
    high = bars.high.rolling(rules.channel_bars).max().shift(1)
    low = bars.low.rolling(rules.channel_bars).min().shift(1)
    volatility = atr(bars, 14)
    average = bars.volume.rolling(rules.volume_bars).mean().shift(1)
    rvol = bars.volume / average.where(average > 0)
    width = bars.high - bars.low
    close_location = (bars.close - bars.low) / width.where(width > 0)
    volume_ok = rvol >= rules.min_rvol if rules.min_rvol else pd.Series(True, index=bars.index)
    sane_range = width <= 2.5 * volatility
    long = (bars.close > high + .1 * volatility) & (bars.close.shift(1) <= high.shift(1)) & (close_location >= .75)
    short = (bars.close < low - .1 * volatility) & (bars.close.shift(1) >= low.shift(1)) & (close_location <= .25)
    result = pd.DataFrame({'side': long.astype(int) - short.astype(int), 'atr_5m': volatility,
                           'channel_high': high, 'channel_low': low, 'rvol': rvol,
                           'signal_close': bars.close}, index=bars.index)
    result.loc[~(volume_ok & sane_range), 'side'] = 0
    return result


def prepare(rows, rules=Rules()):
    rules.validate()
    source = normalize_ohlcv(rows)
    if source.empty or any(source.timestamp.diff().dropna() != MINUTE):
        raise DataError('requires consecutive one-minute candles')
    df = source.reset_index(drop=True).copy()
    df['decision_ms'] = df.timestamp + MINUTE
    def aggregate(minutes):
        bars = source.resample(f'{minutes}min', origin='epoch', label='left', closed='left').agg(
            open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
            close=('close', 'last'), volume=('volume', 'sum'), count=('close', 'count'))
        return bars[bars['count'] == minutes]
    hourly = aggregate(60)
    ema = hourly.close.ewm(span=50, adjust=False).mean()
    context = pd.DataFrame({'decision_ms': hourly.index.as_unit('ns').astype('int64') // 1_000_000 + 60*MINUTE,
                           'trend_side': ((hourly.close > ema) & (ema > ema.shift(1))).astype(int).values
                           - ((hourly.close < ema) & (ema < ema.shift(1))).astype(int).values,
                           'ready': (pd.Series(range(len(hourly)), index=hourly.index) >= 250).values})
    df = pd.merge_asof(df, context, on='decision_ms', direction='backward')
    signals = breakout_bars(aggregate(5), rules)
    signals['decision_ms'] = signals.index.as_unit('ns').astype('int64') // 1_000_000 + 5*MINUTE
    # Exact join: only the minute closing the 5m signal can schedule an entry.
    df = df.merge(signals.reset_index(drop=True), on='decision_ms', how='left')
    df['ready'] = df.ready.eq(True)
    df['side'] = df.side.fillna(0).astype(int)
    df.loc[~df.ready | (df.side != df.trend_side), 'side'] = 0
    return df


def plan_entry(entry, row, rules):
    side = int(row.side)
    if side not in (-1, 1):
        return None
    stop = (min(row.signal_close - rules.atr_multiple*row.atr_5m, row.channel_high - .1*row.atr_5m)
            if side == 1 else max(row.signal_close + rules.atr_multiple*row.atr_5m, row.channel_low + .1*row.atr_5m))
    distance = side*(entry-stop)/entry
    if not math.isfinite(distance) or not rules.min_sl_pct/100 <= distance <= rules.max_sl_pct/100:
        return None
    slip, fee_in, taker = rules.slippage_bps/10000, rules.taker_bps/10000, rules.taker_bps/10000
    stop_fill = stop*(1-side*slip)
    net_loss = -side*(stop_fill/entry-1) + fee_in + stop_fill/entry*taker
    fee_tp = (rules.maker_bps if rules.tp_maker else rules.taker_bps)/10000
    ratio = ((1+fee_in+rules.net_rr*net_loss)/(1-fee_tp) if side == 1
             else (1-fee_in-rules.net_rr*net_loss)/(1+fee_tp))
    target = entry*ratio/(1 if rules.tp_maker else 1-side*slip)
    target = max(target, entry*(1+rules.min_tp_pct/100)) if side == 1 else min(target, entry*(1-rules.min_tp_pct/100))
    tp_distance = side*(target-entry)/entry
    if not math.isfinite(target) or target <= 0 or not 0 < tp_distance <= rules.max_tp_pct/100:
        return None
    return dict(side=side, sl=stop, tp=target, planned_loss_fraction=net_loss,
                planned_sl_pct=100*distance, planned_tp_pct=100*tp_distance,
                signal_atr_5m=float(row.atr_5m), signal_rvol=float(row.rvol) if math.isfinite(row.rvol) else None)


def exit_fill(row, position, rules):
    side = position['side']
    stop, target = position['sl'], position['tp']
    slip = rules.slippage_bps/10000
    stop_hit = row.low <= stop if side == 1 else row.high >= stop
    target_hit = row.high > target if side == 1 else row.low < target
    if not rules.tp_maker:
        target_hit = row.high >= target if side == 1 else row.low <= target
    if int(row.timestamp) >= position['entry_ms'] + rules.hold_minutes*MINUTE:
        return 'TIME', float(row.open)*(1-side*slip), False, 'bar open'
    if side*(row.open-stop) <= 0:
        return 'SL', float(row.open)*(1-side*slip), False, 'bar open'
    if side*(row.open-target) > 0 or (not rules.tp_maker and row.open == target):
        return 'TP', target if rules.tp_maker else float(row.open)*(1-side*slip), False, 'bar open'
    if stop_hit:
        return 'SL', stop*(1-side*slip), bool(target_hit), 'intrabar; sequence unknown'
    if target_hit:
        return 'TP', target*(1 if rules.tp_maker else 1-side*slip), False, 'intrabar; sequence unknown'
    return None


def evaluate(df, start_ms, rules=Rules()):
    rules.validate()
    positions = df.index[df.timestamp == start_ms].tolist()
    if not positions or not bool(df.loc[positions[0], 'ready']):
        raise ValueError('evaluation start must match a minute after hourly warm-up')
    sample = df.iloc[positions[0]:].reset_index(drop=True)
    if len(sample) < 2:
        raise ValueError('at least two evaluation candles required')
    equity = peak = rules.initial_equity
    drawdown = 0.
    trades, daily, equity_daily = [], {}, {}
    pending = position = None
    next_entry = 0
    rejected = candidates = terminal_signals = 0
    fee_in = rules.taker_bps/10000
    rows = list(sample.itertuples(index=False))
    for i, row in enumerate(rows):
        ts = int(row.timestamp)
        day = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
        daily.setdefault(day, 0)
        if pending and pending['fill_index'] == i:
            signal = pending['signal_row']
            entry = float(row.open)*(1+signal.side*rules.slippage_bps/10000)
            plan = plan_entry(entry, signal, rules)
            if plan:
                notional = min(equity*rules.risk_pct/100/plan['planned_loss_fraction'],
                               equity*rules.leverage*rules.max_margin_fraction)
                position = dict(plan, signal_ms=int(signal.decision_ms), entry_ms=ts, entry_price=entry,
                                entry_notional=notional, units=notional/entry, entry_fee=notional*fee_in,
                                funding_cost=0., margin=notional/rules.leverage)
                daily[day] += 1
                next_entry = ts + rules.cooldown_minutes*MINUTE
            else:
                rejected += 1
            pending = None
        if position:
            # Hypothetical stress, not historical funding: charge either side at UTC 0/8/16.
            if ts % (8*60*MINUTE) == 0 and position['entry_ms'] < ts:
                position['funding_cost'] += position['units']*float(row.open)*rules.funding_stress_bps/10000
            fill = exit_fill(row, position, rules)
            if fill is None and i == len(rows)-1:
                fill = ('END', float(row.close)*(1-position['side']*rules.slippage_bps/10000), False, 'final bar close')
            if fill:
                reason, price, ambiguous, precision = fill
                fee_out = position['units']*price*(rules.maker_bps if reason == 'TP' and rules.tp_maker else rules.taker_bps)/10000
                pnl = position['side']*position['units']*(price-position['entry_price'])-position['entry_fee']-fee_out-position['funding_cost']
                equity += pnl
                trades.append(dict(position, exit_bar_ms=ts, exit_price=price, exit_fee=fee_out,
                    exit_time_precision=precision, reason=reason, ambiguous=ambiguous, pnl=pnl,
                    net_notional_return_pct=100*pnl/position['entry_notional'], equity_after=equity))
                position = None
        marked = equity
        if position:
            marked += position['side']*position['units']*(row.close-position['entry_price'])-position['entry_fee']-position['funding_cost']-position['units']*row.close*fee_in
        peak = max(peak, marked)
        drawdown = max(drawdown, 1-marked/peak)
        if marked <= 0:
            raise ValueError('modeled equity exhausted')
        equity_daily[day] = float(marked)
        if row.side:
            candidates += 1
            if not position and not pending and ts+MINUTE >= next_entry:
                fill_index = i+1+rules.delay_minutes
                if fill_index >= len(rows):
                    terminal_signals += 1
                else:
                    fill_day = pd.Timestamp(rows[fill_index].timestamp, unit='ms', tz='UTC').strftime('%Y-%m-%d')
                    if daily.get(fill_day, 0) < rules.daily_cap:
                        pending = dict(fill_index=fill_index, signal_row=row)
    wins = sum(max(t['pnl'], 0) for t in trades)
    losses = -sum(min(t['pnl'], 0) for t in trades)
    return dict(completed_trades=len(trades), qualifying_signals=candidates, rejected_entries=rejected,
                terminal_signals=terminal_signals, final_equity=equity, return_pct=100*(equity/rules.initial_equity-1),
                max_drawdown_pct=100*drawdown, profit_factor=wins/losses if losses else None,
                win_rate_pct=100*sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,
                mean_net_notional_return_pct=sum(t['net_notional_return_pct'] for t in trades)/len(trades) if trades else None,
                long_trades=sum(t['side']==1 for t in trades), short_trades=sum(t['side']==-1 for t in trades),
                ambiguous_trades=sum(t['ambiguous'] for t in trades),
                exits={reason:sum(t['reason']==reason for t in trades) for reason in ('TP','SL','TIME','END')},
                entries_by_utc_day=daily, equity_by_utc_day=equity_daily,
                mean_entries_per_day=sum(daily.values())/len(daily), zero_entry_days=sum(v==0 for v in daily.values()),
                trades=trades)
