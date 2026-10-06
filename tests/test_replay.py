import json
from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock

import pandas as pd
import pytest

from config import Settings
from indicators import compute_macd, detect_macd_signal, signal_audit
from market_data import DataError
from replay import load_rows, main, parse_utc, replay, simulate
from signals import process
from state import State

FIXTURES = Path(__file__).parent/'fixtures'
START = 1767225600000


def sample():
    return load_rows(FIXTURES/'ohlcv.json')


def test_golden_replay_and_independent_pandas_reference():
    df, report = replay(sample(),Settings())
    expected = json.loads((FIXTURES/'events.json').read_text())
    assert len(report['events']) == len(expected) == 8
    for event, golden in zip(report['events'],expected):
        assert event['candle_ms'] == golden['candle_ms']
        assert event['signal'] == golden['signal']
        for key in ('macd','signal_line','hist'):
            assert event[key] == pytest.approx(golden[key],abs=1e-12)
    assert report['audit'] == {'events':8,'buy_signals':4,'sell_signals':4,'last_signal':'SELL'}


def test_export_byte_reproducibility_and_csv(tmp_path):
    one,two = tmp_path/'one.json',tmp_path/'two.json'
    assert main([str(FIXTURES/'ohlcv.json'),'--output',str(one)]) == 0
    assert main([str(FIXTURES/'ohlcv.json'),'--output',str(two)]) == 0
    assert one.read_bytes() == two.read_bytes()
    csv = tmp_path/'input.csv'
    pd.DataFrame(sample(),columns=['timestamp','open','high','low','close','volume']).to_csv(csv,index=False)
    df,report = replay(load_rows(csv),Settings())
    assert report['input_sha256'] == json.loads(one.read_text())['input_sha256']


def test_online_poll_and_restart_equivalence(tmp_path):
    rows = sample()
    df,report = replay(rows,Settings())
    state = State(tmp_path/'state.db')
    cfg = Settings()
    from market_data import normalize_ohlcv
    process(normalize_ohlcv(rows[:139]),cfg,state,START+139*60000+3000,[])
    events = []
    for end in (160,180,220,240):
        batch = normalize_ohlcv(rows[max(0,end-150):end])
        events.extend(process(batch,cfg,state,START+end*60000+3000,[]))
        state.close()
        state = State(tmp_path/'state.db')
        assert process(batch,cfg,state,START+end*60000+3000,[]) == []
    assert [e['event_id'] for e in events] == [e['event_id'] for e in report['events']]
    for a,b in zip(events,report['events']):
        assert (a['macd'],a['signal_line'],a['hist']) == (b['macd'],b['signal_line'],b['hist'])
    state.close()


def test_future_prices_cannot_change_earlier_events():
    rows = sample()
    _, original = replay(rows,Settings())
    changed = [list(row) for row in rows]
    for row in changed[200:]:
        row[1:5] = [900,1100,800,1000]
    _, altered = replay(changed,Settings())
    before = lambda report: [e for e in report['events'] if e['candle_ms'] < START+200*60000]
    assert before(original) == before(altered)


def test_cutoff_ignores_unfinished_cross():
    rows = sample()[:152]
    _,report = replay(rows,Settings(),START+151*60000+30000)
    assert all(e['candle_ms'] < START+151*60000 for e in report['events'])
    assert report['candles'] == 151
    _,report = replay(rows,Settings(),START+152*60000+3000)
    assert report['events'][-1]['candle_ms'] == START+151*60000


@pytest.mark.parametrize('rows', [[],sample()[:138],sample()[:10]+sample()[11:]])
def test_bad_replay(rows):
    with pytest.raises(DataError):
        replay(rows,Settings())


def execution_frame():
    from market_data import normalize_ohlcv
    return normalize_ohlcv([[START+i*60000,op,max(op,close)+1,min(op,close)-1,close,10]
                             for i,(op,close) in enumerate([(10,10),(20,25),(30,15),(40,40),(50,50)])])


def test_next_open_execution_fees_slippage_and_sell_requires_position():
    df = execution_frame()
    events = [dict(candle_ms=START,signal='BUY',event_id='buy'),
              dict(candle_ms=START+2*60000,signal='SELL',event_id='sell'),
              dict(candle_ms=START+3*60000,signal='SELL',event_id='ignored')]
    result = simulate(df,events,START,fee_bps=100,slippage_bps=100,initial_cash=1000)
    assert result['completed_trades'] == 1
    trade = result['trades'][0]
    assert trade['entry_price'] == 20*1.01
    assert trade['exit_price'] == 40*.99
    units = 1000/(20*1.01*1.01)
    assert result['final_marked_equity'] == pytest.approx(units*40*.99*.99)
    assert trade['entry_utc'].startswith('2026-01-01T00:01')
    assert trade['exit_utc'].startswith('2026-01-01T00:03')
    assert result['max_drawdown_pct'] == pytest.approx(40.)
    assert result['benchmark_return_pct'] == pytest.approx((50/(10*1.01*1.01)-1)*100)


def test_evaluation_starts_flat_and_terminal_signal_has_no_fill():
    df = execution_frame()
    events = [dict(candle_ms=START,signal='BUY',event_id='development'),
              dict(candle_ms=START+4*60000,signal='BUY',event_id='last')]
    result = simulate(df,events,START+60000,0,0)
    assert result['completed_trades'] == 0 and result['open_position'] is None
    assert result['final_marked_equity'] == 1000
    events = [dict(candle_ms=START+60000,signal='BUY',event_id='evaluation')]
    result = simulate(df,events,START+60000,0,0)
    assert result['open_position']['entry_price'] == 30
    assert result['completed_trades'] == 0


def test_cli_simulation_and_split_validation(tmp_path):
    output = tmp_path/'report.json'
    common=[str(FIXTURES/'ohlcv.json'),'--output',str(output),'--simulate']
    assert main(common) == 2
    assert main(common+['--evaluation-start','2026-01-01T02:00:00Z']) == 2
    assert main(common+['--evaluation-start','2026-01-01T03:00:00Z']) == 0
    report=json.loads(output.read_text())
    assert report['development']['candles'] == 180
    assert report['simulation']['evaluation_candles'] == 60
    assert report['simulation']['assumptions']
    assert main(common+['--evaluation-start','2026-01-01T03:00:00Z','--fee-bps','nan']) == 2


@pytest.mark.parametrize('value',['2026-01-01','invalid'])
def test_utc_parse_requires_timezone(value):
    with pytest.raises(ValueError):
        parse_utc(value)


def test_indicator_empty_short_nan_and_warmup():
    assert compute_macd(pd.DataFrame({'close':[]})).empty
    assert detect_macd_signal(compute_macd(pd.DataFrame({'close':[1.]}))) is None
    with pytest.raises(ValueError,match='finite'):
        compute_macd(pd.DataFrame({'close':[1.,float('nan')]}))
    df=compute_macd(pd.DataFrame({'close':[1.]*141}))
    assert not df.eligible.iloc[138] and df.eligible.iloc[139]
    assert signal_audit([])['last_signal'] == 'NONE'


def test_network_guard_is_active():
    import socket
    with pytest.raises(AssertionError,match='network access'):
        socket.create_connection(('example.invalid',443))


@pytest.mark.parametrize('fee,slip', [(float('inf'),0),(-1,0),(10000,0),(0,10000),(0,float('nan'))])
def test_invalid_simulation_costs(fee,slip):
    with pytest.raises(ValueError,match='costs'):
        simulate(execution_frame(),[],START,fee,slip)


def test_replay_invalid_files_and_input_protection(tmp_path):
    source = tmp_path/'bad.json'
    source.write_text('{invalid')
    assert main([str(source),'--output',str(tmp_path/'out.json')]) == 2
    source.write_text('[]')
    assert main([str(source),'--output',str(source)]) == 2
    assert source.read_text() == '[]'
    source = tmp_path/'bad.csv'
    source.write_text('bad,columns\n1,2\n')
    assert main([str(source),'--output',str(tmp_path/'out.json')]) == 2


def test_evaluation_prefix_results_do_not_depend_on_future_suffix():
    rows=sample()
    df,report=replay(rows,Settings())
    short_df,short_report=replay(rows[:200],Settings())
    boundary=START+180*60000
    from_full=simulate(df.iloc[:200],report['events'],boundary)
    from_prefix=simulate(short_df,short_report['events'],boundary)
    assert from_full == from_prefix


def test_send_before_ack_crash_repeats_delivery_without_duplicate_event(tmp_path,monkeypatch):
    import main as runner
    from types import SimpleNamespace
    from tests.test_signals import frame
    state=State(tmp_path/'crash.db')
    cfg=Settings()
    process(frame(150),cfg,state,150*60000+3000,[])
    process(frame(152),cfg,state,152*60000+3000,['desktop'])
    monkeypatch.setattr(runner.time,'time',lambda:152*60+3)
    sender=Mock()
    monkeypatch.setattr(runner,'send_desktop_alert',sender)
    monkeypatch.setattr(state,'delivered',Mock(side_effect=KeyboardInterrupt('crash before ack')))
    with pytest.raises(KeyboardInterrupt):
        runner.deliver_pending(state,cfg,SimpleNamespace(no_notifications=False),Mock(),'')
    state.close()
    state=State(tmp_path/'crash.db')
    runner.deliver_pending(state,cfg,SimpleNamespace(no_notifications=False),Mock(),'')
    assert sender.call_count == 2
    assert state.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    assert not state.pending()
    state.close()
