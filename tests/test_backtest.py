from dataclasses import replace
import json
import math

import pandas as pd
import pytest

from backtest import Parameters, main, prepare, simulate
from market_data import DataError

START = 1767225600000


def execution(n=25):
    return pd.DataFrame([dict(timestamp=START+i*60000, open=100., high=100.01,
                              low=99.99, close=100., ready=True, candidate=i == 0)
                         for i in range(n)])


def test_tp_fee_math_and_next_open():
    df = execution()
    df.loc[1, 'high'] = 100.2
    p = Parameters(slippage_bps=0.)
    r = simulate(df, START, p)
    t = r['trades'][0]
    assert t['entry_ms'] == START+60000
    assert t['reason'] == 'TP'
    assert t['entry_fee'] == pytest.approx(.5)
    assert t['exit_fee'] == pytest.approx(.20032)
    assert t['pnl'] == pytest.approx(.89968)
    assert r['final_marked_equity'] == pytest.approx(1000.89968)


def test_ambiguous_stop_first_and_gap_execution():
    df = execution()
    df.loc[1, ['high', 'low']] = [100.2, 99.7]
    r = simulate(df, START, Parameters(slippage_bps=0.))
    assert r['trades'][0]['reason'] == 'SL'
    assert r['ambiguous_trades'] == 1
    assert r['trades'][0]['pnl'] == pytest.approx(-3.69865)
    df = execution()
    df.loc[2, ['open', 'low', 'close']] = [99., 98.9, 99.]
    r = simulate(df, START, Parameters(slippage_bps=0.))
    assert r['trades'][0]['exit_price'] == 99.


def test_time_stop_ignores_deadline_bar_high_and_low():
    df = execution()
    df.loc[18, ['high', 'low']] = [101., 98.]
    r = simulate(df, START, Parameters(slippage_bps=0.))
    t = r['trades'][0]
    assert t['reason'] == 'TIME'
    assert t['exit_bar_ms']-t['entry_ms'] == 17*60000
    assert t['pnl'] == pytest.approx(-1.)


def test_maker_touch_not_filled_and_terminal_position():
    df = execution(3)
    df.loc[1, 'high'] = 100*1.0016
    r = simulate(df, START, Parameters(slippage_bps=0.))
    assert r['completed_trades'] == 0
    assert r['open_position'] is not None
    r = simulate(df, START, Parameters(slippage_bps=0., tp_maker=False))
    assert r['completed_trades'] == 1


def test_daily_cap_cooldown_and_delay():
    df = execution(200)
    df['candidate'] = True
    df['high'] = 100.2
    r = simulate(df, START, Parameters(slippage_bps=0., cooldown_minutes=0, daily_cap=4))
    assert r['completed_trades'] == 4
    r = simulate(df, START, Parameters(slippage_bps=0., cooldown_minutes=60))
    entries = [t['entry_ms'] for t in r['trades']]
    assert all(b-a >= 60*60000 for a,b in zip(entries, entries[1:]))
    r = simulate(execution(), START, Parameters(delay_minutes=2))
    assert r['trades'][0]['entry_ms'] == START+3*60000


def history(n=15500):
    return [[START+i*60000, 100., max(100., c)+.1, min(100., c)-.1, c, 10.]
            for i in range(n) for c in [100 + .2*math.sin(i/20)+i*.0001]]


def test_mtf_future_leakage_and_warmup():
    rows = history()
    full = prepare(rows, Parameters())
    prefix = prepare(rows[:15300], Parameters())
    pd.testing.assert_frame_equal(full.iloc[:15300].reset_index(drop=True), prefix)
    altered = [r[:] for r in rows]
    for r in altered[15300:]:
        r[1:5] = [200., 201., 199., 200.]
    changed = prepare(altered, Parameters())
    pd.testing.assert_frame_equal(full.iloc[:15300], changed.iloc[:15300])
    assert not full.ready.iloc[:15059].any()
    assert full.ready.iloc[15059]
    assert full.ready.iloc[-1]
    with pytest.raises(ValueError, match='warm-up'):
        simulate(full, START, Parameters())
    with pytest.raises(DataError, match='consecutive'):
        prepare(rows[:10]+rows[11:20], Parameters())


def test_cli_reproducible_comparison_and_protection(tmp_path):
    source, output = tmp_path/'input.json', tmp_path/'report.json'
    source.write_text(json.dumps(history()))
    args = [str(source), '--output', str(output), '--evaluation-start',
            '2026-01-11T12:00:00Z', '--data-kind', 'synthetic', '--compare-stops']
    assert main(args) == 0
    first = output.read_bytes()
    assert main(args) == 0
    assert output.read_bytes() == first
    report = json.loads(first)
    assert [r['parameters']['sl_pct'] for r in report['runs']] == [.07, .1, .14]
    assert main([str(source), '--output', str(source), '--evaluation-start',
                 '2026-01-11T12:00:00Z', '--data-kind', 'synthetic']) == 2


@pytest.mark.parametrize('changes', [{'sl_pct':float('nan')}, {'maker_bps':-1.},
                                     {'margin_fraction':2.}, {'fast':26}, {'daily_cap':0}])
def test_bad_parameters(changes):
    with pytest.raises(ValueError):
        replace(Parameters(), **changes).validate()
