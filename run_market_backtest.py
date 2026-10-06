"""Predeclared development comparison, chronological holdout, and cost stress."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from backtest import Parameters, prepare, simulate
from replay import load_rows, parse_utc


def compact(run):
    r = run['results']
    returns = [t['net_notional_return_pct'] for t in r['trades']]
    return dict(sl_pct=run['parameters']['sl_pct'], setup_filter=run['parameters']['setup_filter'],
                completed_trades=r['completed_trades'], return_pct=r['return_pct'],
                win_rate_pct=r['win_rate_pct'], profit_factor=r['profit_factor'],
                max_drawdown_pct=r['max_drawdown_pct'],
                mean_entries_per_day=r['mean_entries_per_observed_day'],
                zero_entry_days=r['zero_entry_days'], exits=r['exits'],
                ambiguous_trades=r['ambiguous_trades'],
                mean_net_notional_return_pct=sum(returns)/len(returns) if returns else None)


def run(input_path, output, development_start, holdout_start):
    source = input_path.read_bytes()
    provenance = json.loads(input_path.with_suffix(input_path.suffix + '.manifest.json').read_text())
    if provenance['sha256'] != hashlib.sha256(source).hexdigest():
        raise ValueError('dataset hash does not match download manifest')
    rows = load_rows(input_path, source)
    base = Parameters()
    # Freeze 6 variants; no tuning to the holdout results.
    prepared = {enabled: prepare(rows, replace(base, setup_filter=enabled)) for enabled in (True, False)}
    development = []
    for enabled in (True, False):
        frame = prepared[enabled]
        frame = frame[frame.timestamp < holdout_start].reset_index(drop=True)
        for stop in (base.sl_pct,):
            p = replace(base, setup_filter=enabled, sl_pct=stop)
            development.append(dict(parameters=asdict(p), results=simulate(frame, development_start, p)))
    def score(run):
        c = compact(run)
        return (c['mean_net_notional_return_pct'] if c['mean_net_notional_return_pct'] is not None else -float('inf'),
                1 <= c['mean_entries_per_day'] <= 4)
    selected = max(development, key=score)
    p = Parameters(**selected['parameters'])
    selected_summary = compact(selected)
    print('Development:', json.dumps([compact(r) for r in development], indent=2), flush=True)
    print('Frozen selected parameters:', json.dumps(asdict(p)), flush=True)
    selected_holdout = dict(parameters=asdict(p), results=simulate(prepared[p.setup_filter], holdout_start, p))
    stress = []
    for label, changed in [('2bps_slippage', replace(p, slippage_bps=2.)),
                           ('1minute_entry_delay', replace(p, delay_minutes=1)),
                           ('taker_tp', replace(p, tp_maker=False))]:
        stress.append(dict(label=label, parameters=asdict(changed),
                           results=simulate(prepared[p.setup_filter], holdout_start, changed)))
    report = dict(dataset=provenance,
        split=dict(development_start_ms=development_start, holdout_start_ms=holdout_start),
        selection_rule='highest mean net return per trade as percent entry notional; 1-4 mean entries/day is secondary; six predeclared variants; ties keep first',
        assumptions=['long-only; 0.16% target; 17m time stop; MACD 12/26/9',
                     '2bps maker TP, 5bps taker entry/SL/time; 1bp slippage per taker fill by default',
                     '100x, 1% account margin per entry, $1000 starting equity per run',
                     'closed higher timeframe joins; next-open entry; hourly indicator warm-up uses preceding history',
                     'SL first for unknown intrabar ordering; gap SL at open; maker TP requires trade-through',
                     'maker fill queue, funding, liquidation, order size rounding, and book depth not modeled',
                     'holdout reserved from parameter selection in this run; neither period is future live evidence',
                     'zero-trade days included; exit timestamps are bars; open positions marked not force-exited',
                     'sensitivity runs do not select another setting'],
        development=development, selected_development_summary=selected_summary,
        holdout=selected_holdout, sensitivity=stress)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print('Holdout:', json.dumps(compact(selected_holdout), indent=2), flush=True)
    print('Sensitivity:', json.dumps([dict(label=r['label'], **compact(r)) for r in stress], indent=2), flush=True)
    print('Report:', output, flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development-start', default='2026-07-01T00:00:00Z')
    parser.add_argument('--holdout-start', default='2026-09-01T00:00:00Z')
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        raise ValueError('output must differ from input')
    start, boundary = parse_utc(args.development_start), parse_utc(args.holdout_start)
    if boundary <= start:
        raise ValueError('holdout must start after development')
    run(args.input, args.output, start, boundary)
