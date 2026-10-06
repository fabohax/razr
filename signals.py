"""Incremental MACD: first-close EMA seeds, persisted across polling windows."""
import hashlib
from datetime import datetime, timezone
from market_data import DURATION_MS, DataError
from state import STRATEGY_VERSION, namespace


def warmup(fast, slow, signal):
    # Five slow spans attenuate the initial EMA seed to about exp(-10).
    return 5 * slow + signal


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', ' UTC')


def process(df, cfg, state, now_ms, channels):
    ns = namespace(cfg)
    old = state.checkpoint(ns)
    if old is None:
        if len(df) < warmup(cfg.macd_fast, cfg.macd_slow, cfg.macd_signal):
            raise DataError('insufficient closed history for EMA warm-up')
        ef = es = float(df.close.iloc[0])
        sig = 0.0
        rows = df.iloc[1:]
    else:
        watermark, ef, es, sig = old
        rows = df[df.timestamp > watermark]
        if rows.empty:
            return []
        if int(rows.timestamp.iloc[0]) != watermark + DURATION_MS:
            raise DataError('unresolved recovery gap exceeds available history; watermark retained')
    events = []
    for row in rows.itertuples():
        previous_hist = ef - es - sig
        ef += 2 / (cfg.macd_fast + 1) * (row.close - ef)
        es += 2 / (cfg.macd_slow + 1) * (row.close - es)
        macd = ef - es
        sig += 2 / (cfg.macd_signal + 1) * (macd - sig)
        hist = macd - sig
        direction = 'BUY' if previous_hist <= 0 < hist else 'SELL' if previous_hist >= 0 > hist else None
        if old is not None and direction:
            ts = int(row.timestamp)
            age = now_ms - ts - DURATION_MS
            event = dict(event_id=hashlib.sha256(f'{ns}:{ts}:{direction}'.encode()).hexdigest(),
                         candle_ms=ts, exchange=cfg.exchange, market='spot', symbol=cfg.symbol,
                         timeframe=cfg.timeframe, strategy_version=STRATEGY_VERSION,
                         parameters=[cfg.macd_fast, cfg.macd_slow, cfg.macd_signal],
                         signal=direction, price=float(row.close), macd=macd, signal_line=sig, hist=hist,
                         open_utc=utc(ts), close_utc=utc(ts + DURATION_MS),
                         recovered=age > DURATION_MS + cfg.close_grace_seconds * 1000,
                         deliverable=age <= cfg.alert_age_limit_seconds * 1000)
            events.append(event)
    state.commit(ns, (int(df.timestamp.iloc[-1]), ef, es, sig), events, channels)
    return events
