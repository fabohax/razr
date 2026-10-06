from dataclasses import replace

import pandas as pd
import pytest

from backtest import Parameters
from strategy_v2 import Rules, atr, entry_confirmation, evaluate, plan_entry, prepare
from tests.test_backtest import START, execution, history


def test_wilder_seed_and_smoothing():
    frame = pd.DataFrame({'high':[2.,2.,9.,9.], 'low':[0.,0.,8.,8.], 'close':[1.,1.,8.5,8.5]})
    result = atr(frame, 3)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2] == 4.
    assert result.iloc[3] == pytest.approx(3.)


def test_waits_for_second_histogram_close_and_price_confirmation():
    df = execution(25)
    df['MACD'] = -1.
    df['MACD_Hist'] = -1.
    df.loc[23, 'MACD_Hist'] = .2
    df.loc[24, 'MACD_Hist'] = .3
    df['volume'] = 10.
    df.loc[24, ['close', 'high']] = [100.1,100.2]
    flags = entry_confirmation(df)
    assert not flags.iloc[23]
    assert flags.iloc[24]
    df.loc[24, 'MACD_Hist'] = -.1
    assert not entry_confirmation(df).any()
    df.loc[24, 'MACD_Hist'] = .3
    df.loc[24, 'close'] = 100.
    assert not entry_confirmation(df).any()


@pytest.mark.parametrize('tp_maker', [True, False])
def test_fixed_tp_and_stop_relative_to_actual_fill(tp_maker):
    row = pd.Series({'close':100., 'swing_low_5m':99.8, 'atr_5m':.1})
    p = Parameters(tp_maker=tp_maker)
    rules = Rules(net_rr=1.5, min_tp_pct=.1)
    plan = plan_entry(100., row, p, rules)
    assert plan['sl'] == pytest.approx(99.73)
    assert plan['planned_sl_pct'] == .27
    assert plan['tp'] == pytest.approx(100.16)
    assert plan['planned_tp_pct'] == .16
    assert plan_entry(100., row, replace(p, tp_pct=.25), rules)['tp'] == pytest.approx(100.25)
    assert plan_entry(101., row, p, rules)['sl'] == pytest.approx(101 * .9973)
    assert plan_entry(99., row, p, rules)['sl'] == pytest.approx(99 * .9973)
    assert plan_entry(100., row, replace(p, sl_pct=.5), rules)['sl'] == pytest.approx(99.5)


def test_planner_uses_actual_fill_after_entry_gap():
    df = execution()
    df['swing_low_5m'] = 90.
    df['atr_5m'] = 10.
    df.loc[1, 'open'] = 101.
    df.loc[1, 'high'] = 102.
    df.loc[1, 'low'] = 100.9
    result = evaluate(df, START)
    trade = result['trades'][0]
    assert trade['sl'] == pytest.approx(trade['entry_price'] * .9973)
    assert trade['tp'] == pytest.approx(trade['entry_price'] * 1.0016)
    assert trade['reason'] == 'TP'
    assert result['rejected_entries'] == 0


@pytest.mark.parametrize('family', ['impulse', 'censored'])
def test_closed_mtf_context_future_invariance_and_bearish_gate(family):
    rows = history()
    rules = Rules(family=family)
    full = prepare(rows, rules)
    prefix = prepare(rows[:15317], rules)
    pd.testing.assert_frame_equal(full.iloc[:15317].reset_index(drop=True), prefix)
    changed = [r[:] for r in rows]
    for r in changed[15317:]:
        r[1:5] = [90.,91.,89.,90.]
    alternate = prepare(changed, rules)
    pd.testing.assert_frame_equal(full.iloc[:15317], alternate.iloc[:15317])
    assert not full.ready.iloc[:15059].any()
    assert full.ready.iloc[-1]
    assert not full.loc[~full.gate_15m, 'candidate'].any()
    assert not full.loc[~full.gate_60m, 'candidate'].any()
    assert not full.loc[full.impulse_15m == -1, 'candidate'].any()
    assert not full.loc[full.impulse_60m == -1, 'candidate'].any()
    if family == 'impulse':
        normalized = prepare(rows, Rules(family='macdv'))
        assert not normalized.loc[~full.candidate, 'candidate'].any()


@pytest.mark.parametrize('changes', [{'net_rr':float('nan')}, {'family':'invalid'},
                                     {'min_sl_pct':.5}, {'max_tp_pct':0.}])
def test_invalid_rules(changes):
    with pytest.raises(ValueError):
        replace(Rules(), **changes).validate()


def test_zero_filter_uses_cross_candle_not_confirmation():
    df = execution(25)
    df['MACD'] = -1.
    df['MACD_Hist'] = -1.
    df.loc[23:24, 'MACD_Hist'] = [.2, .3]
    df['volume'] = 10.
    df.loc[24, ['close', 'high', 'MACD']] = [100.1, 100.2, 1.]
    assert entry_confirmation(df).iloc[24]
    df.loc[23, 'MACD'] = .01
    assert not entry_confirmation(df).any()
    df.loc[23, 'MACD'] = 0.
    assert entry_confirmation(df).iloc[24]
