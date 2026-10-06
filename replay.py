"""Offline MACD audit and optional next-open long-only spot simulation."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import sys

import pandas as pd

from config import ConfigError, Settings, load_config
from indicators import signal_audit
from market_data import DataError, closed_candles, DURATION_MS
from signals import process, utc, warmup
from state import State, STRATEGY_VERSION


def parse_utc(value):
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            raise ValueError('timezone required')
        return int(stamp.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('timestamp must include a UTC offset, e.g. 2026-01-01T00:00:00Z') from exc


def load_rows(path, content=None):
    content = path.read_bytes() if content is None else content
    text = content.decode('utf-8')
    if path.suffix.lower() == '.csv':
        df = pd.read_csv(io.StringIO(text))
        columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if list(df.columns) != columns:
            raise DataError('CSV columns must be timestamp,open,high,low,close,volume')
        return df.values.tolist()
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise DataError('JSON must contain an array of six-value OHLCV rows')
    return rows


def replay(rows, cfg, as_of_ms=None):
    from market_data import normalize_ohlcv
    normalized = normalize_ohlcv(rows)
    if normalized.empty:
        raise DataError('empty replay input')
    # Offline files assert historical completeness by default. No host-clock use.
    if as_of_ms is None:
        as_of_ms = int(normalized.timestamp.iloc[-1]) + DURATION_MS + cfg.close_grace_seconds * 1000 + 1
    # Historical data need not be fresh; all other live eligibility checks apply.
    df = closed_candles(rows, as_of_ms, cfg.close_grace_seconds, stale_after_seconds=10**15)
    baseline = warmup(cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    state = State(':memory:')
    try:
        process(df.iloc[:baseline], cfg, state, as_of_ms, [])
        events = process(df.iloc[baseline:], cfg, state, as_of_ms, []) if len(df) > baseline else []
    finally:
        state.close()
    canonical = json.dumps(df.reset_index(drop=True).values.tolist(), separators=(',', ':'), allow_nan=False)
    report = dict(format_version=1, strategy_version=STRATEGY_VERSION,
                  market=[cfg.exchange, 'spot', cfg.symbol, cfg.timeframe],
                  parameters=[cfg.macd_fast, cfg.macd_slow, cfg.macd_signal],
                  input_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                  as_of_utc=utc(as_of_ms), candles=len(df), warmup_candles=baseline,
                  coverage_open_utc=utc(int(df.timestamp.iloc[0])),
                  coverage_close_utc=utc(int(df.timestamp.iloc[-1])+DURATION_MS),
                  audit=signal_audit(events), events=events)
    return df, report


def simulate(df, events, evaluation_start_ms, fee_bps=10., slippage_bps=5., initial_cash=1000.):
    """No shorting: signal at close, fill at following candle open, all cash in/out."""
    if any(not math.isfinite(x) or x < 0 for x in (fee_bps, slippage_bps)) or max(fee_bps, slippage_bps) >= 10000:
        raise ValueError('costs must be finite nonnegative bps below 10000')
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError('initial cash must be finite and positive')
    sample = df[df.timestamp >= evaluation_start_ms]
    if len(sample) < 2 or int(sample.timestamp.iloc[0]) != evaluation_start_ms:
        raise ValueError('evaluation start must match a candle opening timestamp with at least two evaluation candles')
    fee, slip = fee_bps / 10000, slippage_bps / 10000
    eligible = {e['candle_ms']: e for e in events if e['candle_ms'] >= evaluation_start_ms}
    cash, units = initial_cash, 0.
    peak, drawdown = initial_cash, 0.
    trades = []
    entry = None
    for row in sample.itertuples():
        event = eligible.get(int(row.timestamp)-DURATION_MS)
        if event and event['signal'] == 'BUY' and not units:
            price = float(row.open)*(1+slip)
            units = cash / (price*(1+fee))
            entry = dict(signal_event_id=event['event_id'], entry_utc=utc(int(row.timestamp)),
                         entry_price=price, units=units, entry_cash=cash)
            cash = 0.
        elif event and event['signal'] == 'SELL' and units:
            price = float(row.open)*(1-slip)
            cash = units*price*(1-fee)
            trades.append(dict(entry, exit_event_id=event['event_id'], exit_utc=utc(int(row.timestamp)),
                               exit_price=price, pnl=cash-entry['entry_cash']))
            units, entry = 0., None
        # Mark to close, without assuming liquidation or intrabar price order.
        equity = cash + units*float(row.close)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)
    final = cash+units*float(sample.close.iloc[-1])
    benchmark_units = initial_cash/(float(sample.open.iloc[0])*(1+slip)*(1+fee))
    benchmark = benchmark_units*float(sample.close.iloc[-1])
    return dict(assumptions=['long-only spot; no leverage or shorting',
                            'all cash allocated; no sizing, minimum order or liquidity constraints',
                            'signal confirmed at close; execution at following candle open',
                            'costs applied to executed orders; no forced final liquidation',
                            'drawdown uses candle-close marked equity, not intrabar extremes',
                            'benchmark buys at first evaluation open with identical entry costs',
                            'evaluation starts flat; development signals cannot open evaluation positions',
                            'synthetic or historical results do not establish profitability'],
                evaluation_open_utc=utc(evaluation_start_ms),
                evaluation_close_utc=utc(int(sample.timestamp.iloc[-1])+DURATION_MS),
                evaluation_candles=len(sample),
                initial_cash=initial_cash, fee_bps=fee_bps, slippage_bps=slippage_bps,
                completed_trades=len(trades), open_position=entry,
                final_marked_equity=final, return_pct=(final/initial_cash-1)*100,
                max_drawdown_pct=drawdown*100, benchmark_return_pct=(benchmark/initial_cash-1)*100,
                trades=trades)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='historical JSON OHLCV array or CSV with timestamp milliseconds')
    parser.add_argument('--output', type=Path, required=True, help='JSON report including exported events')
    parser.add_argument('--data-kind', choices=('historical', 'synthetic'), default='historical',
                        help='caller-specified provenance label (not independently verified)')
    parser.add_argument('--config', type=Path, help='validated strategy YAML; never used for network access')
    parser.add_argument('--as-of', help='explicit timezone-aware historical cutoff; excludes unfinished candles')
    parser.add_argument('--simulate', action='store_true', help='include separate long-only evaluation')
    parser.add_argument('--evaluation-start', help='first evaluation candle open, with timezone; required for simulation')
    parser.add_argument('--fee-bps', type=float, default=10.)
    parser.add_argument('--slippage-bps', type=float, default=5.)
    parser.add_argument('--initial-cash', type=float, default=1000.)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError('output must differ from input')
        cfg = load_config(args.config) if args.config else Settings()
        source = args.input.read_bytes()
        rows = load_rows(args.input, source)
        df, report = replay(rows, cfg, parse_utc(args.as_of) if args.as_of else None)
        report['data_kind'] = args.data_kind
        report['source_sha256'] = hashlib.sha256(source).hexdigest()
        if args.simulate:
            if not args.evaluation_start:
                raise ValueError('--simulate requires --evaluation-start; choose the split before inspecting results')
            start = parse_utc(args.evaluation_start)
            minimum = warmup(cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
            development = df[df.timestamp < start]
            if len(development) < minimum:
                raise ValueError('development period must contain the EMA warm-up before evaluation starts')
            report['development'] = dict(candles=len(development),
                close_utc=utc(int(development.timestamp.iloc[-1])+DURATION_MS),
                audit=signal_audit([e for e in report['events'] if e['candle_ms'] < start]))
            report['simulation'] = simulate(df, report['events'], start, args.fee_bps,
                                            args.slippage_bps, args.initial_cash)
        elif args.evaluation_start:
            raise ValueError('--evaluation-start requires --simulate')
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
        print(f"Replay complete: {len(df)} candles, {len(report['events'])} events; {args.output}")
        return 0
    except (ValueError, ConfigError, DataError, OSError) as exc:
        print(f'Replay error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
