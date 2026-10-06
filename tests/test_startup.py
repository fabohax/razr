from dataclasses import asdict
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import ConfigError, Settings, application_paths, load_config, save_config, validate_config
from utils import connect_okx, validate_exchange


@pytest.mark.parametrize('raw', [None, [], 'bad', {'macd_fast': 0}, {'macd_fast': 26},
    {'sleep_seconds': 0}, {'sleep_seconds': True}, {'limit': 36}, {'limit': 301},
    {'resume_grace_seconds': -1}, {'notify_urgency': 'urgent'}, {'debug': 'false'},
    {'exchange': 'binance'}, {'symbol': 'BTC/USDT:USDT'}, {'timeframe': '5m'},
    {'authenticated': True}, {'authenticated': True, 'api_key': 'EXCHANGE_API_KEY'},
    {'typo': 1}])
def test_invalid_settings(raw):
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_example_public_and_roundtrip(tmp_path):
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.yaml.example')
    assert not cfg.authenticated
    assert cfg.api_key == cfg.api_secret == cfg.api_passphrase == ''
    save_config(tmp_path / 'config.yaml', cfg)
    assert load_config(tmp_path / 'config.yaml') == cfg


def metadata():
    return SimpleNamespace(has={'fetchOHLCV': True},
        markets={'BTC/USDT': {'spot': True, 'active': True}}, timeframes={'1m': '1m'})


@pytest.mark.parametrize('change', ['capability', 'market', 'type', 'inactive', 'timeframe'])
def test_metadata_rejection(change):
    exchange = metadata()
    if change == 'capability':
        exchange.has = {}
    elif change == 'market':
        exchange.markets = {}
    elif change == 'type':
        exchange.markets['BTC/USDT']['spot'] = False
    elif change == 'inactive':
        exchange.markets['BTC/USDT']['active'] = False
    else:
        exchange.timeframes = {}
    with pytest.raises(ConfigError):
        validate_exchange(exchange, Settings())


def test_public_credentials_never_forwarded(monkeypatch):
    constructor = Mock(return_value=metadata())
    constructor.return_value.load_markets = Mock()
    monkeypatch.setattr('utils.ccxt.okx', constructor)
    connect_okx(validate_config({'api_key': 'legacy', 'api_secret': 'legacy'}), logging.getLogger())
    assert 'apiKey' not in constructor.call_args.args[0]
    constructor.return_value.load_markets.assert_called_once()


def test_paths_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    first = application_paths()
    monkeypatch.chdir(tmp_path)
    assert application_paths() == first
    assert first.state.parent == first.log.parent == first.config.parent == first.directory


def test_once_and_invalid_cli(tmp_path, monkeypatch):
    import main
    paths = application_paths(tmp_path)
    save_config(paths.config, Settings())
    exchange = Mock()
    exchange.fetch_ohlcv.return_value = [[i * 60000, 1, 4, 1, 1 + i / 100, 10] for i in range(200)]
    exchange.fetch_ticker.return_value = {'last': 3}
    monkeypatch.setattr(main, 'connect_okx', lambda *_: exchange)
    desktop = Mock()
    sound = Mock()
    monkeypatch.setattr(main, 'send_desktop_alert', desktop)
    monkeypatch.setattr(main, 'play_sound', sound)
    monkeypatch.setattr(main.time, 'time', lambda: 200 * 60 + 3)
    assert main.main(['--app-dir', str(tmp_path), '--once', '--no-notifications']) == 0
    desktop.assert_not_called()
    sound.assert_not_called()
    exchange.fetch_ohlcv.return_value = []
    assert main.main(['--app-dir', str(tmp_path), '--once']) == 1
    paths.config.write_text('sleep_seconds: 0')
    assert main.main(['--app-dir', str(tmp_path)]) == 2


def test_gui_save_failure_blocks_launch(monkeypatch):
    from gui import RazrGUI
    gui = object.__new__(RazrGUI)
    gui.process = None
    gui.save_config = Mock(return_value=False)
    gui._build_bot_command = Mock(side_effect=AssertionError('must not launch'))
    gui.start_bot()
    gui._build_bot_command.assert_not_called()


def test_gui_uses_shared_validation():
    from gui import FIELD_SPECS, RazrGUI
    gui = object.__new__(RazrGUI)
    cfg = asdict(Settings())
    cfg['macd_fast'] = 26
    gui.vars = {name: Mock(get=Mock(return_value=cfg[name])) for name, _ in FIELD_SPECS}
    gui.exchange_var = Mock(get=Mock(return_value='okx'))
    gui.symbol_var = Mock(get=Mock(return_value='BTC/USDT'))
    with pytest.raises(ConfigError, match='less than'):
        gui._collect_config()


def test_gui_write_error_returns_failure(tmp_path, monkeypatch):
    from gui import RazrGUI
    gui = object.__new__(RazrGUI)
    gui.paths = application_paths(tmp_path)
    gui._collect_config = Mock(return_value=Settings())
    monkeypatch.setattr('gui.save_config', Mock(side_effect=OSError('read-only file system')))
    dialog = Mock()
    monkeypatch.setattr('gui.messagebox.showerror', dialog)
    assert gui.save_config() is False
    dialog.assert_called_once()


def test_gui_runner_paths(tmp_path, monkeypatch):
    from gui import RazrGUI
    gui = object.__new__(RazrGUI)
    gui.paths = application_paths(tmp_path)
    monkeypatch.chdir(tmp_path)
    command = gui._build_bot_command()
    assert Path(command[2]).is_absolute()
    assert command[-4:] == ['--app-dir', str(gui.paths.directory), '--config', str(gui.paths.config)]
