"""Run v2 family variants with fixed TP and freeze selection before validation."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import statistics

from backtest import Parameters
from replay import load_rows, parse_utc
from strategy_v2 import Rules, evaluate, prepare


def summary(result):
    trades = result['trades']
    metrics = {key: result[key] for key in ('completed_trades', 'qualifying_signals',
        'rejected_entries', 'win_rate_pct', 'profit_factor', 'return_pct',
        'max_drawdown_pct', 'mean_entries_per_observed_day', 'zero_entry_days', 'exits', 'ambiguous_trades')}
    metrics['mean_net_notional_return_pct'] = statistics.mean(t['net_notional_return_pct'] for t in trades) if trades else None
    for name in ('planned_sl_pct', 'planned_tp_pct'):
        metrics[name + '_median'] = statistics.median(t[name] for t in trades) if trades else None
        metrics[name + '_range'] = [min(t[name] for t in trades), max(t[name] for t in trades)] if trades else None
    return metrics


def load_verified(path):
    source = path.read_bytes()
    manifest = json.loads(path.with_suffix(path.suffix + '.manifest.json').read_text())
    if hashlib.sha256(source).hexdigest() != manifest['sha256']:
        raise ValueError('source hash differs from manifest')
    if manifest['instrument'] != 'BTC-USDT-SWAP' or manifest['timeframe'] != '1m' or not manifest['confirmed_only']:
        raise ValueError('requires confirmed BTC-USDT-SWAP 1m data')
    return load_rows(path, source), manifest


def run(source_path, output, prior=None, recent=None, families=('impulse', 'macdv')):
    rows, manifest = load_verified(source_path)
    p = Parameters()
    start = parse_utc('2026-04-01T00:00:00Z')
    validation_start = parse_utc('2026-05-16T00:00:00Z')
    final_start = parse_utc('2026-06-01T00:00:00Z')
    frames = {family: prepare(rows, Rules(family=family)) for family in families}
    development = []
    for family in families:
        rules = Rules(family=family)
        frame = frames[family]
        sample = frame[frame.timestamp < validation_start].reset_index(drop=True)
        results = evaluate(sample, start, rules, p)
        entry = dict(rules=asdict(rules), parameters=asdict(p), summary=summary(results), results=results)
        development.append(entry)
        print('Development:', json.dumps(dict(rules=asdict(rules), summary=entry['summary'])), flush=True)
    supported = [r for r in development if r['results']['completed_trades'] >= 15]
    candidates = supported or [r for r in development if r['results']['completed_trades'] > 0]
    selected = max(candidates or development, key=lambda r:
                   r['summary']['mean_net_notional_return_pct'] if r['summary']['mean_net_notional_return_pct'] is not None else -float('inf'))
    rules = Rules(**selected['rules'])
    selection = dict(rules=asdict(rules), parameters=asdict(p), source_sha256=manifest['sha256'],
        selection_rule='highest development mean net return per entry notional; minimum 15 trades; if none qualified, descriptive diagnostic only',
        status='development-selected; profitability unestablished' if supported else 'insufficient development sample; diagnostic only',
        development_summary=selected['summary'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    print('Frozen before validation:', json.dumps(selection), flush=True)
    frame = frames[rules.family]
    validation = evaluate(frame[frame.timestamp < final_start].reset_index(drop=True), validation_start, rules, p)
    final = evaluate(frame, final_start, rules, p)
    sensitivity = []
    for label, changed in [('2bps_slippage', replace(p, slippage_bps=2.)),
                           ('1minute_entry_delay', replace(p, delay_minutes=1)),
                           ('taker_tp', replace(p, tp_maker=False))]:
        result = evaluate(frame, final_start, rules, changed)
        sensitivity.append(dict(label=label, parameters=asdict(changed), summary=summary(result), results=result))
    report = dict(strategy='mtf-confirmed-macd-v2', dataset=manifest, selection=selection,
                  families=list(families),
                  development=development, validation=dict(summary=summary(validation), results=validation),
                  final_check=dict(summary=summary(final), results=final), sensitivity=sensitivity,
                  assumptions=['rules and search space documented in STRATEGY_V2.md',
                               'zero minimum daily entries; daily cap four; long only; 17m time stop',
                               'fixed SL 0.27% below actual entry',
                               'fixed TP 0.16% above actual entry; fees and slippage affect realized PnL',
                               'maker TP queue/funding/liquidation unmodeled; 1% account margin at 100x',
                               'tp_pct/sl_pct in Parameters set fixed levels relative to actual entry',
                               ('censored is a follow-up exploration after the strict experiment; its validation/final intervals were already observed'
                                if 'censored' in families else 'family comparison with fixed 0.16% TP'),
                               'earlier historical intervals not previously evaluated, but later history informed refinement; retrospective check, not forward validation'])
    if prior:
        old_rows, old_manifest = load_verified(prior)
        old_frame = prepare(old_rows, rules)
        result = evaluate(old_frame, parse_utc('2026-07-01T00:00:00Z'), rules, p)
        report['reused_period_diagnostic'] = dict(dataset=old_manifest, summary=summary(result), results=result,
                                                 label='previously observed July-October; not an untouched holdout')
        if recent:
            recent_rows, recent_manifest = load_verified(recent)
            extended = prepare(old_rows + recent_rows, rules)
            lo, hi = parse_utc('2026-10-06T01:50:00Z'), parse_utc('2026-10-06T02:14:00Z')
            crossed = (extended.MACD_Hist.shift(1) <= 0) & (extended.MACD_Hist > 0)
            window = extended[(extended.decision_ms >= lo) & (extended.decision_ms <= hi) & crossed]
            columns = ['timestamp', 'decision_ms', 'close', 'MACD', 'MACD_Hist', 'trigger',
                       'gate_5m', 'gate_15m', 'gate_60m', 'candidate',
                       'impulse_5m', 'impulse_15m', 'impulse_60m',
                       'macd_hist_5m', 'macd_hist_15m', 'macd_hist_60m']
            report['screenshot_window_audit'] = dict(dataset=recent_manifest, rules=asdict(rules),
                bullish_crosses=window[columns].to_dict(orient='records'),
                caveat='B/S marker origin not established; this checks market crosses near screenshot times')
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print('Validation:', json.dumps(report['validation']['summary'], indent=2), flush=True)
    print('Final check:', json.dumps(report['final_check']['summary'], indent=2), flush=True)
    for item in sensitivity:
        print('Sensitivity:', item['label'], json.dumps(item['summary']), flush=True)
    if 'reused_period_diagnostic' in report:
        print('Reused period:', json.dumps(report['reused_period_diagnostic']['summary']), flush=True)
    if 'screenshot_window_audit' in report:
        print('Screenshot window:', json.dumps(report['screenshot_window_audit']['bullish_crosses']), flush=True)
    print('Report:', output, flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reused-data', type=Path)
    parser.add_argument('--screenshot-data', type=Path)
    parser.add_argument('--families', nargs='+', choices=('impulse', 'macdv', 'censored'), default=['impulse', 'macdv'])
    args = parser.parse_args()
    if args.output.resolve() in {p.resolve() for p in (args.input, args.reused_data, args.screenshot_data) if p}:
        raise ValueError('output must differ from input datasets')
    run(args.input, args.output, args.reused_data, args.screenshot_data, tuple(args.families))
