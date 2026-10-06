from dataclasses import replace
import math
import sqlite3

import pandas as pd
import pytest

from config import Settings, validate_config, ConfigError
from indicators import compute_macd, detect_macd_signal
from market_data import closed_candles, normalize_ohlcv, DataError
from signals import process, warmup
from state import State, namespace


def rows(n=220):
    return [[i*60000, 100, 120, 80, 100+10*math.sin(i/4), 10] for i in range(n)]


def frame(n):
    return normalize_ohlcv(rows(n))


def test_normalization_and_closed_boundary():
    data = rows(3)
    df = normalize_ohlcv([data[2], data[0], data[1], data[1]])
    assert len(df) == 3 and str(df.index.tz) == 'UTC'
    assert len(closed_candles(data, 182000)) == 2  # strict grace boundary
    assert len(closed_candles(data, 182001)) == 3  # closed last row retained
    assert len(closed_candles(data, 150000)) == 2  # unfinished row excluded


@pytest.mark.parametrize('bad', [[], [[0,1,2]], [[0,1,2,1,float('nan'),1]],
    [[0,1,2,1,float('inf'),1]], [[0,1,2,1,3,1]], [[0,1,2,1,1,-1]],
    [[1,1,2,1,1,1]], [[True,1,2,1,1,1]], [[0,1,2,1,1,1],[0,1,2,1,2,1]]])
def test_bad_data(bad):
    with pytest.raises(DataError):
        closed_candles(bad, 65000)


def test_stale_and_gap():
    with pytest.raises(DataError, match='stale'):
        closed_candles(rows(3), 400000)
    with pytest.raises(DataError, match='missing'):
        closed_candles([rows(3)[0], rows(3)[2]], 185000)


def test_fixed_numerical_fixture_and_equality():
    df = compute_macd(pd.DataFrame({'close':[1.,2.,3.,2.,1.]}), 2,3,2)
    assert df.MACD.tolist() == pytest.approx([0, 1/6, 11/36, 13/216, -217/1296])
    assert df.MACD_Signal.tolist() == pytest.approx([0, 1/9, 13/54, 13/108, -139/1944])
    assert detect_macd_signal(df) is None  # not warmed up
    crossing = pd.DataFrame({'close':[1.,2.], 'MACD':[0.,1.], 'MACD_Signal':[0.,0.], 'MACD_Hist':[0.,1.]})
    assert detect_macd_signal(crossing) is None  # above zero
    crossing.loc[1, 'MACD'] = 0
    assert detect_macd_signal(crossing) is None


def test_extra_history_convergence():
    data = pd.DataFrame({'close':[100+math.sin(i/8) for i in range(500)]})
    full = compute_macd(data)
    short = compute_macd(data.iloc[-200:])
    assert abs(full.MACD.iloc[-1]-short.MACD.iloc[-1]) < 1e-6
    assert abs(full.MACD_Signal.iloc[-1]-short.MACD_Signal.iloc[-1]) < 1e-6


def test_replay_restart_identity_and_saved_ema(tmp_path):
    cfg = Settings()
    path = tmp_path/'state.db'
    state = State(path)
    assert process(frame(150), cfg, state, 150*60000+3000, ['console_log']) == []
    events = process(frame(220), cfg, state, 220*60000+3000, ['console_log'])
    assert [e['candle_ms']//60000 for e in events] == [151,176,201]
    assert [e['signal'] for e in events] == ['BUY','BUY','BUY']
    assert all('strong' not in e for e in events)
    assert all(e['recovered'] for e in events)
    assert sum(e['deliverable'] for e in events) == 0
    expected = compute_macd(frame(220))
    cp = state.checkpoint(namespace(cfg))
    assert cp[1]-cp[2] == pytest.approx(expected.MACD.iloc[-1])
    assert cp[3] == pytest.approx(expected.MACD_Signal.iloc[-1])
    state.close()
    state = State(path)
    assert process(frame(220), cfg, state, 220*60000+3000, ['console_log']) == []
    assert state.db.execute('SELECT count(*) FROM events').fetchone()[0] == 3
    assert process(frame(220), replace(cfg, macd_fast=10), state, 220*60000+3000, []) == []
    assert state.db.execute('SELECT count(*) FROM processing').fetchone()[0] == 2
    state.close()


def test_jobs_atomic_and_latest_event(tmp_path):
    cfg = Settings(alert_age_limit_seconds=10000)
    state = State(tmp_path/'state.db')
    process(frame(150), cfg, state, 150*60000+3000, [])
    events = process(frame(175), cfg, state, 175*60000+3000, ['console_log','desktop'])
    assert len(state.pending()) == 2*len(events)
    assert process(frame(175), cfg, state, 175*60000+3000, ['console_log']) == []
    cp = state.checkpoint(namespace(cfg))
    event = dict(events[0], event_id='invalid-new', candle_ms=999999)
    with pytest.raises(sqlite3.IntegrityError):
        state.commit(namespace(cfg), (cp[0]+60000,*cp[1:]), [event], [None])
    assert state.checkpoint(namespace(cfg)) == cp
    assert state.db.execute("SELECT count(*) FROM events WHERE id='invalid-new'").fetchone()[0] == 0
    with pytest.raises(DataError, match='recovery gap'):
        process(frame(500).iloc[-200:], cfg, state, 500*60000+3000, [])
    assert state.checkpoint(namespace(cfg)) == cp
    state.close()


def test_warmup_and_config(tmp_path):
    state = State(tmp_path/'state.db')
    with pytest.raises(DataError, match='warm-up'):
        process(frame(warmup(12,26,9)-1), Settings(), state, 200*60000, [])
    for raw in [{'limit':140}, {'close_grace_seconds':-1}, {'stale_after_seconds':60}, {'alert_age_limit_seconds':-1}]:
        with pytest.raises(ConfigError):
            validate_config(raw)
    state.close()


def test_unfinished_cross_does_not_advance_or_alert(tmp_path):
    cfg = Settings()
    state = State(tmp_path/'state.db')
    process(frame(150), cfg, state, 150*60000+3000, [])
    # Candle 151 is a BUY crossing but remains open at this clock time.
    df = closed_candles(rows(152), 151*60000+30000)
    assert process(df, cfg, state, 151*60000+30000, ['console_log']) == []
    assert state.checkpoint(namespace(cfg))[0] == 150*60000
    df = closed_candles(rows(152), 152*60000+3000)
    events = process(df, cfg, state, 152*60000+3000, ['console_log'])
    assert len(events) == 1 and events[0]['signal'] == 'BUY'
    assert not events[0]['recovered'] and events[0]['deliverable']
    assert len(state.pending()) == 1
    state.close()


def test_delivery_failure_preserves_event_job(tmp_path, monkeypatch):
    import main
    from types import SimpleNamespace
    from unittest.mock import Mock
    state = State(tmp_path/'state.db')
    cfg = Settings()
    process(frame(150), cfg, state, 150*60000+3000, [])
    process(frame(152), cfg, state, 152*60000+3000, ['desktop'])
    monkeypatch.setattr(main.time, 'time', lambda: 152*60+3)
    monkeypatch.setattr(main, 'send_desktop_alert', Mock(side_effect=RuntimeError('unavailable')))
    main.deliver_pending(state, cfg, SimpleNamespace(no_notifications=False), Mock(), '')
    assert len(state.pending()) == 1
    assert state.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    state.close()


@pytest.mark.parametrize('direction', ['BUY', 'SELL'])
@pytest.mark.parametrize('level', [-1., 0., 1.])
def test_cross_zero_line_filter(direction, level, tmp_path):
    # Arrange a real incremental cross at each side of zero, including equality.
    cfg = Settings(macd_fast=2, macd_slow=3, macd_signal=2)
    state = State(tmp_path / 'zero.db')
    sign = 1 if direction == 'BUY' else -1
    state.commit(namespace(cfg), (0, 100 + level - sign, 100., level - .5*sign), [], [])
    df = normalize_ohlcv([[60000, 100., 120., 80., 100 + 4*level + 2*sign, 10.]])
    events = process(df, cfg, state, 123000, ['console_log'])
    assert [e['signal'] for e in events] == ([direction] if level <= 0 else [])
    assert len(state.pending()) == len(events)
    assert state.checkpoint(namespace(cfg))[0] == 60000
    batch = pd.DataFrame({'close': [100., 100.], 'MACD': [2*level, level],
                          'MACD_Signal': [2*level + sign, level - sign],
                          'MACD_Hist': [-sign, sign]})
    event = detect_macd_signal(batch)
    assert (event['signal'] if event else None) == (direction if level <= 0 else None)
    state.close()
