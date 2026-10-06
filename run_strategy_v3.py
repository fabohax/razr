"""Frozen breakout/volume experiment with new historical evaluation intervals."""
import argparse
from dataclasses import asdict, replace
import itertools
import json
from pathlib import Path
import statistics

from replay import parse_utc
from run_strategy_v2 import load_verified
from strategy_v3 import Rules, evaluate, prepare


def summarize(result):
    report={k:v for k,v in result.items() if k not in ('trades','entries_by_utc_day','equity_by_utc_day')}
    trades=result['trades']
    report['mean_realized_r']=statistics.mean(t['pnl']/(t['entry_notional']*t['planned_loss_fraction']) for t in trades) if trades else None
    report['total_fees']=sum(t['entry_fee']+t['exit_fee'] for t in trades)
    report['total_funding_stress']=sum(t['funding_cost'] for t in trades)
    report['gross_pnl_after_slippage']=sum(t['side']*t['units']*(t['exit_price']-t['entry_price']) for t in trades)
    for key in ('planned_sl_pct','planned_tp_pct','signal_rvol'):
        values=[t[key] for t in trades if t[key] is not None]
        report[key+'_median']=statistics.median(values) if values else None
    return report


def run(input_path,output):
    rows,manifest=load_verified(input_path)
    start=parse_utc('2025-12-01T00:00:00Z')
    validation_start=parse_utc('2026-02-01T00:00:00Z')
    final_start=parse_utc('2026-03-01T00:00:00Z')
    if manifest['start_utc']!='2025-11-20T00:00:00 UTC' or manifest['end_exclusive_utc']!='2026-03-20T00:00:00 UTC':
        raise ValueError('this frozen experiment requires the declared November 20-March 20 dataset')
    frames={volume:prepare(rows,Rules(min_rvol=volume)) for volume in (0.,1.5,2.)}
    development=[]
    for volume,rr,hold in itertools.product((0.,1.5,2.),(1.,1.5),(60,120)):
        rules=Rules(min_rvol=volume,net_rr=rr,hold_minutes=hold)
        sample=frames[volume]
        sample=sample[sample.timestamp<validation_start].reset_index(drop=True)
        result=evaluate(sample,start,rules)
        entry=dict(rules=asdict(rules),summary=summarize(result),results=result)
        development.append(entry)
        print('Development:',json.dumps(dict(rvol=volume,net_rr=rr,hold=hold,summary=entry['summary'])),flush=True)
    supported=[r for r in development if r['summary']['completed_trades']>=30]
    available=supported or [r for r in development if r['summary']['completed_trades']>0]
    selected=max(available or development,key=lambda r:r['summary']['mean_realized_r'] if r['summary']['mean_realized_r'] is not None else -float('inf'))
    rules=Rules(**selected['rules'])
    selection=dict(rules=asdict(rules),source_sha256=manifest['sha256'],
        rule='highest development mean realized net R among >=30-trade variants; fallback insufficient-sample diagnostic; ties keep first',
        status='selected from development; profitability unestablished' if supported else 'insufficient sample; diagnostic only',
        development_summary=selected['summary'])
    output.parent.mkdir(parents=True,exist_ok=True)
    output.with_suffix('.selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    print('Frozen before later periods:',json.dumps(selection),flush=True)
    frame=frames[rules.min_rvol]
    validation=evaluate(frame[frame.timestamp<final_start].reset_index(drop=True),validation_start,rules)
    final=evaluate(frame,final_start,rules)
    ablation=[]
    for volume in (0.,1.5,2.):
        changed=replace(rules,min_rvol=volume)
        result=evaluate(frames[volume],final_start,changed)
        ablation.append(dict(rules=asdict(changed),summary=summarize(result),results=result))
    stress=[]
    for label,changed in [('2bps_slippage',replace(rules,slippage_bps=2.)),
                          ('5minute_entry_delay',replace(rules,delay_minutes=5)),
                          ('taker_tp',replace(rules,tp_maker=False)),
                          ('hypothetical_1bp_funding',replace(rules,funding_stress_bps=1.))]:
        result=evaluate(frame,final_start,changed)
        stress.append(dict(label=label,rules=asdict(changed),summary=summarize(result),results=result))
    report=dict(strategy='trend-volume-breakout-v3',dataset=manifest,
        protocol='STRATEGY_V3.md; 12 variants; no selection using validation/final/ablation/stress',
        interpretation='new previously unevaluated historical block, but design informed by later 2026 observations; retrospective, not a forward paper test',
        development=development,selection=selection,
        validation=dict(summary=summarize(validation),results=validation),
        final_check=dict(summary=summarize(final),results=final),volume_ablation=ablation,sensitivity=stress,
        assumptions=['long and short; confirmed 5m range breakout and 1h EMA50 context; no MACD entry',
            'channel and RVOL mean exclude the breakout candle; contract volume, not aggressor delta',
            'next 1m open entry; frozen structural/ATR stop; net RR target; period-end taker closure labeled END',
            'planned SL risk 0.25% account; 10x; max margin fraction 10%; cap notional at equity',
            '2bp maker TP and 5bp taker entry/SL/time/END; 1bp adverse taker slippage',
            'SL first for unknown intrabar order; maker TP must trade through limit, no queue model',
            'drawdown uses minute-close marked equity including estimated taker close fees',
            'baseline excludes funding; funding stress charges either side 1bp at UTC 0/8/16, not historical funding',
            'no liquidation/mark price, depth, minimum-size/contract-rounding or actual fill model'])
    output.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print('Validation:',json.dumps(report['validation']['summary'],indent=2),flush=True)
    print('Final check:',json.dumps(report['final_check']['summary'],indent=2),flush=True)
    for item in ablation:
        print('Volume ablation:',item['rules']['min_rvol'],json.dumps(item['summary']),flush=True)
    for item in stress:
        print('Stress:',item['label'],json.dumps(item['summary']),flush=True)
    print('Report:',output,flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        raise ValueError('output must differ from input')
    run(args.input,args.output)
