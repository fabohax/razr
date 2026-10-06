import json
from unittest.mock import Mock

import pytest

import fetch_history
from fetch_history import download
from replay import parse_utc

START = parse_utc('2026-01-01T00:00:00Z')


def page(rows):
    response = Mock()
    response.json.return_value = {'code': '0', 'data': rows}
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    return session


def candle(ts, confirm='1'):
    return [str(ts), '100', '101', '99', '100', '2', '.02', '2', confirm]


def test_download_verified_manifest(monkeypatch, tmp_path):
    session = page([candle(START+60000), candle(START)])
    monkeypatch.setattr(fetch_history.requests, 'Session', lambda: session)
    path = tmp_path/'data.json'
    manifest = download(START, START+120000, path)
    assert manifest['candles'] == 2
    assert manifest['instrument'] == 'BTC-USDT-SWAP'
    assert manifest['confirmed_only']
    assert json.loads(path.read_text())[0] == [START, 100., 101., 99., 100., 2.]
    with pytest.raises(ValueError, match='already exists'):
        download(START, START+120000, path)


@pytest.mark.parametrize('rows,message', [([candle(START)], 'missing'),
                                         ([candle(START+60000),candle(START,'0')], 'unconfirmed')])
def test_reject_incomplete_history(monkeypatch, tmp_path, rows, message):
    monkeypatch.setattr(fetch_history.requests, 'Session', lambda: page(rows))
    path = tmp_path/'data.json'
    with pytest.raises(ValueError, match=message):
        download(START, START+120000, path)
    assert not path.exists()
