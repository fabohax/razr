from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from strategy_v3 import Rules, breakout_bars, evaluate, exit_fill, plan_entry, prepare
from tests.test_backtest import START, history


def signal(side=1):
    return SimpleNamespace(side=side, signal_close=100., atr_5m=.2,
                           channel_high=99.9, channel_low=100.1, rvol=2.)


@pytest.mark.parametrize('side', [1,-1])
@pytest.mark.parametrize('maker', [True,False])
def test_net_ratio_is_exact_for_both_directions(side, maker):
    rules=Rules(net_rr=1.5, tp_maker=maker)
    p=plan_entry(100.,signal(side),rules)
    assert p is not None
    sl_fill=p['sl']*(1-side*.0001)
    tp_fill=p['tp']*(1 if maker else 1-side*.0001)
    loss=-side*(sl_fill/100-1)+.0005+sl_fill/100*.0005
    gain=side*(tp_fill/100-1)-.0005-tp_fill/100*(.0002 if maker else .0005)
    assert gain/loss == pytest.approx(1.5)
    assert loss == pytest.approx(p['planned_loss_fraction'])
    assert plan_entry(103. if side==1 else 97.,signal(side),rules) is None


def test_volume_mean_and_channel_exclude_current_bar():
    bars=pd.DataFrame({'open':[100.]*30,'high':[100.1]*30,'low':[99.9]*30,
                       'close':[100.]*30,'volume':[10.]*30})
    bars.loc[29,['high','close','volume']]=[100.4,100.4,20.]
    result=breakout_bars(bars,Rules())
    assert result.rvol.iloc[-1] == 2.
    assert result.channel_high.iloc[-1] == 100.1
    assert result.side.iloc[-1] == 1
    bars.loc[29,'volume']=14.
    assert breakout_bars(bars,Rules()).side.iloc[-1] == 0
    assert breakout_bars(bars,Rules(min_rvol=0.)).side.iloc[-1] == 1


@pytest.mark.parametrize('side', [1,-1])
def test_stop_first_gap_and_deadline(side):
    rules=Rules(hold_minutes=60)
    pos=dict(side=side,sl=99. if side==1 else 101.,tp=101. if side==1 else 99.,entry_ms=START)
    row=SimpleNamespace(timestamp=START,open=100.,high=102.,low=98.)
    result=exit_fill(row,pos,rules)
    assert result[0] == 'SL' and result[2]
    row.open=98. if side==1 else 102.
    result=exit_fill(row,pos,rules)
    assert result[1] == pytest.approx(row.open*(1-side*.0001))
    row.timestamp=START+60*60000
    row.open=100.
    assert exit_fill(row,pos,rules)[0] == 'TIME'


def execution(n=70, side=1):
    return pd.DataFrame([dict(timestamp=START+i*60000,decision_ms=START+(i+1)*60000,
        open=100.,high=100.01,low=99.99,close=100.,volume=10.,ready=True,
        side=side if i==0 else 0,signal_close=100.,atr_5m=.2,
        channel_high=99.9,channel_low=100.1,rvol=2.) for i in range(n)])


@pytest.mark.parametrize('side',[1,-1])
def test_risk_budget_directional_pnl_and_terminal_costs(side):
    df=execution(side=side)
    df.loc[1,'high' if side==1 else 'low']=102. if side==1 else 98.
    rules=Rules(net_rr=1.,max_margin_fraction=1.,slippage_bps=0.)
    result=evaluate(df,START,rules)
    t=result['trades'][0]
    assert t['entry_notional']*t['planned_loss_fraction'] == pytest.approx(2.5)
    assert t['pnl'] == pytest.approx(2.5)
    assert t['reason']=='TP'
    assert (result['long_trades'],result['short_trades']) == ((1,0) if side==1 else (0,1))
    r=evaluate(execution(3,side),START,Rules())
    assert r['exits']['END'] == 1
    assert r['trades'][0]['pnl'] < 0
    assert r['final_equity'] == pytest.approx(1000+r['trades'][0]['pnl'])


def test_warmup_no_future_leakage_and_single_5m_signal():
    rows=history(15600)
    full=prepare(rows)
    prefix=prepare(rows[:15317])
    pd.testing.assert_frame_equal(full.iloc[:15317].reset_index(drop=True),prefix)
    changed=[r[:] for r in rows]
    for r in changed[15317:]:
        r[1:6]=[150.,160.,140.,155.,999999.]
    alternative=prepare(changed)
    pd.testing.assert_frame_equal(full.iloc[:15317],alternative.iloc[:15317])
    assert not full.ready.iloc[:15059].any()
    assert all(full.loc[full.side!=0,'decision_ms']%300000==0)


def test_funding_stress_and_daily_cap():
    df=execution(180)
    # Start one minute before a hypothetical settlement.
    df.timestamp -= 2*60000
    df.decision_ms -= 2*60000
    base=evaluate(df,START-2*60000,Rules())
    stressed=evaluate(df,START-2*60000,Rules(funding_stress_bps=1.))
    assert stressed['trades'][0]['funding_cost'] > 0
    assert stressed['final_equity'] < base['final_equity']
    df=execution(100)
    df['side']=1
    df['high']=102.
    r=evaluate(df,START,Rules(cooldown_minutes=0))
    assert sum(r['entries_by_utc_day'].values())==4


@pytest.mark.parametrize('changes',[{'min_rvol':float('nan')},{'net_rr':0.},{'risk_pct':101.},
                                     {'min_sl_pct':2.},{'daily_cap':0}])
def test_validation(changes):
    with pytest.raises(ValueError):
        replace(Rules(),**changes).validate()
