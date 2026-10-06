"""Strict UTC normalization and eligibility for the supported one-minute market."""
import math
import numbers
import pandas as pd

DURATION_MS = 60_000


class DataError(ValueError):
    pass


def normalize_ohlcv(rows):
    clean = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 6:
            raise DataError('malformed OHLCV row: expected six numeric values')
        if any(isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v) for v in row):
            raise DataError('OHLCV values must be finite numbers')
        ts, op, high, low, close, volume = row
        if ts < 0 or ts % DURATION_MS or min(op, high, low, close) <= 0 or volume < 0:
            raise DataError('invalid timestamp, price or volume')
        if not low <= min(op, close) <= max(op, close) <= high:
            raise DataError('invalid OHLC relationships')
        values = tuple(row)
        if ts in clean and clean[ts] != values:
            raise DataError(f'conflicting duplicate candle at {ts}')
        clean[int(ts)] = values
    df = pd.DataFrame([clean[t] for t in sorted(clean)], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.index = pd.to_datetime(df.timestamp, unit='ms', utc=True)
    return df


def closed_candles(rows, now_ms, close_grace_seconds=2, stale_after_seconds=120):
    df = normalize_ohlcv(rows)
    cutoff = now_ms - close_grace_seconds * 1000
    df = df[df.timestamp + DURATION_MS < cutoff]
    if df.empty:
        raise DataError('no confirmed closed candles')
    if now_ms - (int(df.timestamp.iloc[-1]) + DURATION_MS) > stale_after_seconds * 1000:
        raise DataError('stale candle data; processing and live alerts suppressed')
    if any(df.timestamp.diff().dropna() != DURATION_MS):
        raise DataError('unresolved missing candle interval; processing stopped')
    return df
