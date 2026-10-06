import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import ccxt
import pytest

import alerts
import main
import runtime
from config import Settings, application_paths, save_config, validate_config, ConfigError
from signals import process
from state import State
from tests.test_signals import frame, rows


class FakeTime:
    def __init__(self, wall=152*60+3):
        self.wall = wall
        self.mono = 100.
        self.waits = []
        self.finished = False

    def wait(self, seconds):
        self.waits.append(seconds)
        self.wall += seconds
        self.mono += seconds
        if len(self.waits) > 30:
            raise AssertionError('runner failed to reach expected outcome')

    def stopped(self):
        return self.finished

    def install(self, monkeypatch):
        monkeypatch.setattr(main.time, 'time', lambda: self.wall)
        monkeypatch.setattr(main.time, 'monotonic', lambda: self.mono)


def args(once=False, disabled=True):
    return SimpleNamespace(once=once, no_notifications=disabled)


def queued(tmp_path):
    state = State(tmp_path/'state.db')
    cfg = Settings()
    process(frame(150), cfg, state, 150*60000+3000, [])
    process(frame(152), cfg, state, 152*60000+3000, ['desktop'])
    return state, cfg


def test_retry_persistence_due_times_and_terminal_failure(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    state, cfg = queued(tmp_path)
    clock = runtime.RetryClock()
    send = Mock(side_effect=alerts.DeliveryError('private token must never be stored'))
    monkeypatch.setattr(main, 'send_desktop_alert', send)
    monkeypatch.setattr(main, 'backoff', lambda *a: 5)
    logger = Mock()
    main.deliver_pending(state, cfg, args(disabled=False), logger, '', clock)
    job = state.db.execute('SELECT retry_count,next_retry_at,last_error FROM deliveries').fetchone()
    assert job == (1, fake.wall+5, 'DeliveryError')
    main.deliver_pending(state, cfg, args(disabled=False), logger, '', clock)
    assert send.call_count == 1
    # Wall-clock movement doesn't move a deadline in the current process.
    fake.wall += 50
    main.deliver_pending(state, cfg, args(disabled=False), logger, '', clock)
    assert send.call_count == 1
    fake.wall -= 50
    state.close()
    state = State(tmp_path/'state.db')
    for attempt in range(2,6):
        fake.wait(5)
        main.deliver_pending(state, cfg, args(disabled=False), logger, '', runtime.RetryClock())
    assert send.call_count == 5
    assert state.db.execute('SELECT status,retry_count FROM deliveries').fetchone() == ('failed',5)
    assert 'private token' not in str(logger.mock_calls)
    assert state.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    state.close()


def test_capability_failure_and_expiration(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    state, cfg = queued(tmp_path)
    monkeypatch.setattr(main, 'send_desktop_alert', Mock(side_effect=alerts.UnavailableChannel('no desktop')))
    main.deliver_pending(state, cfg, args(disabled=False), Mock(), '')
    assert state.db.execute('SELECT status FROM deliveries').fetchone()[0] == 'failed'
    state.db.execute("UPDATE deliveries SET status='pending'")
    state.db.commit()
    fake.wall += 301
    main.deliver_pending(state, cfg, args(disabled=True), Mock(), '')
    assert state.db.execute('SELECT status FROM deliveries').fetchone()[0] == 'expired'
    state.close()


def test_phase2_database_migration(tmp_path):
    path = tmp_path/'old.db'
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE deliveries(event_id TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(event_id,channel)); INSERT INTO deliveries VALUES ('old','desktop','pending');")
    db.close()
    state = State(path)
    assert state.db.execute('SELECT event_id,retry_count,next_retry_at FROM deliveries').fetchone() == ('old',0,0)
    state.close()


@pytest.mark.parametrize('error', [subprocess.TimeoutExpired('notify-send',10), subprocess.CalledProcessError(1,'notify-send')])
def test_subprocess_failures_are_visible(monkeypatch, error):
    runner = Mock(side_effect=error)
    monkeypatch.setattr(alerts.subprocess, 'run', runner)
    with pytest.raises(alerts.DeliveryError):
        alerts.run_command(['notify-send','test'])
    assert runner.call_args.kwargs['check'] is True
    assert runner.call_args.kwargs['timeout'] == 10


def test_capabilities_and_no_false_sound_success(monkeypatch):
    monkeypatch.setattr(alerts.sys, 'platform', 'linux')
    monkeypatch.setattr(alerts.shutil, 'which', lambda _: None)
    assert alerts.capability('console_log') is None
    assert 'notify-send' in alerts.capability('desktop')
    with pytest.raises(alerts.UnavailableChannel):
        alerts.play_sound('/missing/sound.oga')
    monkeypatch.setattr(alerts.sys, 'platform', 'win32')
    assert 'Linux' in alerts.capability('desktop')


def test_backoff_rate_limit_and_monotonic_resume(monkeypatch):
    monkeypatch.setattr(runtime.random, 'uniform', lambda lo,hi: hi)
    assert [runtime.backoff(i,5,30) for i in range(1,6)] == [5,10,20,30,30]
    assert runtime.backoff(1,5,30,60) == 60
    exchange = SimpleNamespace(last_response_headers={'Retry-After':'60'})
    assert runtime.retry_after(exchange,30) == 60
    exchange.last_response_headers = {'Retry-After':'invalid'}
    assert runtime.retry_after(exchange,30) == 0
    fake = FakeTime()
    fake.install(monkeypatch)
    wall, mono = fake.wall, fake.mono
    fake.wait(30)
    assert not runtime.resumed(wall, mono,10)
    fake.wall += 300
    assert runtime.resumed(wall,mono,10)


def test_initial_and_poll_outages_then_recovery(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    paths = application_paths(tmp_path)
    # Preexisting checkpoint ensures reconnection processes missed candles.
    state = State(paths.state)
    process(frame(150), Settings(), state, 150*60000+3000, [])
    state.close()
    exchange = Mock()
    exchange.fetch_ohlcv.side_effect = [ccxt.RequestTimeout('SECRET'), rows(152)]
    connection = Mock(side_effect=[ccxt.NetworkError('SECRET'), exchange, exchange])
    monkeypatch.setattr(main, 'connect_okx', connection)
    monkeypatch.setattr(main, 'backoff', lambda *a: 2)
    logger = Mock()
    original = main.process
    def successful(*a):
        events = original(*a)
        fake.finished = True
        return events
    monkeypatch.setattr(main, 'process', successful)
    assert main.run(Settings(), paths, args(), logger, fake) == 0
    assert connection.call_count == 3 and len(fake.waits) == 4
    state = State(paths.state)
    assert state.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    state.close()
    assert 'SECRET' not in str(logger.mock_calls)
    exchange.close.assert_called()


def test_stale_input_blocks_queue_and_watermark(tmp_path, monkeypatch):
    fake = FakeTime(wall=200*60)
    fake.install(monkeypatch)
    paths = application_paths(tmp_path)
    state = State(paths.state)
    process(frame(150), Settings(), state, 150*60000+3000, [])
    state.close()
    exchange = Mock()
    exchange.fetch_ohlcv.return_value = rows(152)
    monkeypatch.setattr(main, 'connect_okx', lambda *_: exchange)
    delivery = Mock()
    monkeypatch.setattr(main, 'deliver_pending', delivery)
    assert main.run(Settings(), paths, args(once=True), Mock(), fake) == 1
    delivery.assert_not_called()
    state = State(paths.state)
    assert state.db.execute('SELECT watermark FROM processing').fetchone()[0] == 149*60000
    state.close()


def test_rate_limit_preserves_exchange_and_retry_after(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    exchange = Mock()
    exchange.last_response_headers = {'Retry-After':'3'}
    exchange.fetch_ohlcv.side_effect = [ccxt.RateLimitExceeded('secret'),rows(152)]
    connection = Mock(return_value=exchange)
    monkeypatch.setattr(main, 'connect_okx', connection)
    monkeypatch.setattr(runtime.random, 'uniform', lambda a,b: a)
    original = main.process
    def success(*a):
        result = original(*a)
        fake.finished = True
        return result
    monkeypatch.setattr(main, 'process', success)
    assert main.run(Settings(), application_paths(tmp_path), args(), Mock(),fake) == 0
    assert connection.call_count == 1
    assert sum(fake.waits) == 3


def test_lock_exclusion_and_release(tmp_path):
    path = tmp_path/'runner.lock'
    with runtime.RunnerLock(path):
        command = [sys.executable,'-c', 'from runtime import RunnerLock; import sys;\ntry:\n with RunnerLock(sys.argv[1]): pass\nexcept RuntimeError: sys.exit(7)',str(path)]
        assert subprocess.run(command).returncode == 7
    with runtime.RunnerLock(path):
        pass


def test_stop_handlers_and_rotation(tmp_path):
    original = signal.getsignal(signal.SIGTERM)
    with runtime.Stop() as stop:
        os.kill(os.getpid(),signal.SIGTERM)
        assert stop.stopped() and stop.wait(100)
    assert signal.getsignal(signal.SIGTERM) == original
    from utils import setup_logger
    logger = setup_logger(str(tmp_path/'razr.log'))
    handler = logger.handlers[1]
    handler.maxBytes = 100
    for _ in range(5):
        logger.info('test rotation content')
    assert (tmp_path/'razr.log.1').exists()
    assert handler.backupCount == 3


@pytest.mark.parametrize('raw', [{'retry_base_seconds':0},{'retry_max_seconds':1},{'delivery_max_attempts':0}, {'health_interval_seconds':0}, {'sound_notifications':'yes'}])
def test_recovery_config_validation(raw):
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_suspend_reconnects_and_catches_up_in_order(tmp_path, monkeypatch):
    fake = FakeTime(wall=150*60+3)
    fake.install(monkeypatch)
    exchange = Mock()
    exchange.fetch_ohlcv.side_effect = [rows(150), rows(182)]
    connection = Mock(return_value=exchange)
    monkeypatch.setattr(main, 'connect_okx', connection)
    def suspend(seconds):
        fake.wall += 32*60
        fake.mono += seconds
        fake.waits.append(seconds)
    fake.wait = suspend
    original = main.process
    batches = []
    def record(*a):
        events = original(*a)
        batches.append(events)
        if len(batches) == 2:
            fake.finished = True
        return events
    monkeypatch.setattr(main, 'process', record)
    paths = application_paths(tmp_path)
    logger = Mock()
    assert main.run(Settings(), paths, args(), logger, fake) == 0
    assert connection.call_count == 2
    assert [e['candle_ms']//60000 for e in batches[1]] == [151,163,176]
    assert all(e['recovered'] for e in batches[1])
    assert any('discontinuity' in str(call) for call in logger.warning.call_args_list)


def test_headless_does_not_probe_or_dispatch_desktop(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    exchange = Mock()
    exchange.fetch_ohlcv.return_value = rows(152)
    monkeypatch.setattr(main,'connect_okx',lambda *_:exchange)
    probe = Mock(return_value=None)
    monkeypatch.setattr(main,'capability',probe)
    monkeypatch.setattr(main,'send_desktop_alert',Mock(side_effect=AssertionError('desktop disabled')))
    monkeypatch.setattr(main,'play_sound',Mock(side_effect=AssertionError('sound disabled')))
    assert main.run(Settings(),application_paths(tmp_path),args(once=True),Mock(),fake) == 0
    probe.assert_called_once_with('console_log','')


def test_fatal_startup_and_once_outage_do_not_retry(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    connection = Mock(side_effect=ccxt.AuthenticationError('SECRET'))
    monkeypatch.setattr(main,'connect_okx',connection)
    logger = Mock()
    assert main.run(Settings(),application_paths(tmp_path),args(),logger,fake) == 2
    assert connection.call_count == 1 and not fake.waits
    connection.side_effect = ccxt.RequestTimeout('SECRET')
    assert main.run(Settings(),application_paths(tmp_path),args(once=True),logger,fake) == 1
    assert not fake.waits and 'SECRET' not in str(logger.mock_calls)


def test_real_sigterm_interrupts_backoff_and_releases_lock(tmp_path):
    paths = application_paths(tmp_path)
    save_config(paths.config, Settings())
    code = '''import main, ccxt, threading, os, signal, sys

def fail(*a):
    threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    raise ccxt.NetworkError('simulated outage')
main.connect_okx = fail
sys.exit(main.main(['--app-dir',sys.argv[1],'--no-notifications']))
'''
    result = subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stderr
    assert 'Runner stopped; state closed' in result.stdout
    with runtime.RunnerLock(tmp_path/'runner.lock'):
        state = State(paths.state)
        assert state.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        state.close()


def test_requeue_failed_retains_event_identity(tmp_path, monkeypatch):
    fake = FakeTime()
    fake.install(monkeypatch)
    state, cfg = queued(tmp_path)
    event_id = state.db.execute('SELECT id FROM events').fetchone()[0]
    state.failed_attempt(event_id,'desktop','UnavailableChannel',fake.wall,5,5,permanent=True)
    assert state.requeue_failed() == 1
    assert state.retry_count(event_id,'desktop') == 0
    sender = Mock()
    monkeypatch.setattr(main,'send_desktop_alert',sender)
    main.deliver_pending(state,cfg,args(disabled=False),Mock(),'')
    sender.assert_called_once()
    assert state.db.execute('SELECT status FROM deliveries').fetchone()[0] == 'delivered'
    assert state.db.execute('SELECT id FROM events').fetchone()[0] == event_id
    state.close()


def test_metadata_rate_limit_preserves_server_delay(monkeypatch):
    from utils import connect_okx
    exchange = Mock()
    exchange.last_response_headers = {'Retry-After':'600'}
    exchange.load_markets.side_effect = ccxt.RateLimitExceeded('private response')
    monkeypatch.setattr('utils.ccxt.okx',lambda _:exchange)
    with pytest.raises(ccxt.RateLimitExceeded) as failure:
        connect_okx(Settings(),Mock())
    assert failure.value.retry_after_seconds == 600
    exchange.close.assert_called_once()
