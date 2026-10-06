"""Research adaptation: Elder impulse / MACD-V, confirmed entries, structural ATR stops.

Original Python implementation; not an exact copy of a third-party trading script.
Sources and predeclared evaluation design are in STRATEGY_V2.md.
"""
from dataclasses import dataclass
import math

import pandas as pd

from backtest import MINUTE, Parameters, simulate
from indicators import compute_macd
from market_data import DataError, normalize_ohlcv
from signals import warmup


@dataclass(frozen=True)
class Rules:
    family: str = 'impulse'
    atr_multiple: float = 1.
    net_rr: float = 1.
    min_sl_pct: float = .10
    max_sl_pct: float = .35
    min_tp_pct: float = .30
    max_tp_pct: float = .80

    def validate(self):
        if self.family not in ('impulse', 'macdv', 'censored'):
            raise ValueError('family must be impulse, macdv or censored')
        for name in ('atr_multiple', 'net_rr', 'min_sl_pct', 'max_sl_pct', 'min_tp_pct', 'max_tp_pct'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not self.min_sl_pct <= self.max_sl_pct < 100 or not self.min_tp_pct <= self.max_tp_pct < 100:
            raise ValueError('invalid SL/TP distance bounds')


def atr(df, period):
    """Wilder ATR, seeded by the first period's mean true range."""
    previous = df.close.shift(1)
    tr = pd.concat([df.high-df.low, (df.high-previous).abs(), (df.low-previous).abs()], axis=1).max(axis=1)
    seeded = tr.copy()
    seeded.iloc[:period-1] = float('nan')
    if len(seeded) >= period:
        seeded.iloc[period-1] = tr.iloc[:period].mean()
    return seeded.ewm(alpha=1/period, adjust=False).mean()


def entry_confirmation(df):
    """Second positive histogram close after a cross, closing above cross bar high."""
    cross = (df.MACD_Hist.shift(1) <= 0) & (df.MACD_Hist > 0) & (df.MACD <= 0)
    ema = df.close.ewm(span=20, adjust=False).mean()
    volume = df.volume.rolling(20).mean().shift(1)
    return (cross.shift(1, fill_value=False) & (df.MACD_Hist > 0)
            & (df.close > df.high.shift(1)) & (df.close > ema)
            & (df.volume >= volume))


def prepare(rows, rules=Rules()):
    rules.validate()
    source = normalize_ohlcv(rows)
    if source.empty or any(source.timestamp.diff().dropna() != MINUTE):
        raise DataError('input must contain consecutive one-minute candles')
    df = compute_macd(source)
    df['decision_ms'] = df.timestamp + MINUTE
    df['trigger'] = entry_confirmation(df)
    for minutes in (5, 15, 60):
        bars = source.resample(f'{minutes}min', origin='epoch', label='left', closed='left').agg(
            open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
            close=('close', 'last'), volume=('volume', 'sum'), count=('close', 'count'))
        bars = compute_macd(bars[bars['count'] == minutes])
        ema13 = bars.close.ewm(span=13, adjust=False).mean()
        ema20 = bars.close.ewm(span=20, adjust=False).mean()
        ema50 = bars.close.ewm(span=50, adjust=False).mean()
        rising = bars.MACD_Hist > bars.MACD_Hist.shift(1)
        green = (ema13 > ema13.shift(1)) & rising
        red = (ema13 < ema13.shift(1)) & (bars.MACD_Hist < bars.MACD_Hist.shift(1))
        ready = pd.Series(range(len(bars)), index=bars.index) >= max(warmup(12, 26, 9), 250 if minutes == 60 else 139)
        if minutes == 60:
            gate = green & (bars.MACD > 0) & (bars.close > ema50) & (ema50 > ema50.shift(1))
            if rules.family == 'censored':
                gate = ~red & (bars.close > ema50) & (ema50 > ema50.shift(1))
            if rules.family == 'macdv':
                strength = 100 * bars.MACD / atr(bars, 26)
                gate &= strength.between(50, 150)
        elif minutes == 15:
            gate = green & (bars.MACD_Hist > 0) & (bars.close > ema20) & (ema20 > ema50)
            if rules.family == 'censored':
                gate = ~red & (bars.close > ema50) & (ema20 > ema50)
        else:
            # Recovery after touching EMA20 in the last six completed 5m bars.
            pullback = (bars.low <= ema20).rolling(6).max().eq(1)
            gate = green & (bars.MACD_Hist > 0) & (bars.close > ema20) & pullback
            if rules.family == 'censored':
                gate = rising & (bars.close > ema20) & pullback
        context = pd.DataFrame({'decision_ms': bars.index.as_unit('ns').astype('int64') // 1_000_000 + minutes * MINUTE,
                                f'gate_{minutes}m': (ready & gate).values,
                                f'ready_{minutes}m': ready.values,
                                f'impulse_{minutes}m': (green.astype(int) - red.astype(int)).values,
                                f'macd_hist_{minutes}m': bars.MACD_Hist.values})
        if minutes == 5:
            context['atr_5m'] = atr(bars, 14).values
            context['swing_low_5m'] = bars.low.rolling(3).min().values
        df = pd.merge_asof(df.reset_index(drop=True), context, on='decision_ms', direction='backward')
    for name in [c for c in df if c.startswith(('gate_', 'ready_'))]:
        df[name] = df[name].eq(True)
    df['ready'] = df.eligible & df.ready_5m & df.ready_15m & df.ready_60m
    df['candidate'] = df.ready & df.trigger & df.gate_60m & df.gate_15m & df.gate_5m
    return df


def plan_entry(entry, signal_row, parameters, rules):
    """Set fixed SL and TP relative to the actual purchase fill."""
    stop = entry * (1 - parameters.sl_pct / 100)
    distance = parameters.sl_pct
    target = entry * (1 + parameters.tp_pct / 100)
    return dict(sl=stop, tp=target, planned_sl_pct=distance,
                planned_tp_pct=parameters.tp_pct,
                signal_atr_5m=signal_row.atr_5m, signal_swing_low_5m=signal_row.swing_low_5m)


def evaluate(df, start_ms, rules=Rules(), parameters=Parameters()):
    rules.validate()
    return simulate(df, start_ms, parameters,
                    entry_plan=lambda entry, row, p: plan_entry(entry, row, p, rules))
