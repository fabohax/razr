"""Download confirmed OKX BTC-USDT-SWAP 1m history, with provenance and gap checks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

import requests

from market_data import normalize_ohlcv
from replay import parse_utc
from signals import utc

ENDPOINT = 'https://www.okx.com/api/v5/market/history-candles'


def download(start, end, output):
    if start % 60000 or end % 60000 or end <= start:
        raise ValueError('start/end must be minute aligned with end after start')
    if end > int(time.time() * 1000) - 60000:
        raise ValueError('end must exclude the current minute')
    output = Path(output)
    manifest = output.with_suffix(output.suffix + '.manifest.json')
    if output.exists() or manifest.exists():
        raise ValueError('output/manifest already exists; choose a new path')
    lock = threading.Lock()
    next_request = [0.]
    requests_count = [0]

    def fetch_window(bounds):
        lo, hi = bounds
        cursor = hi
        found = {}
        with requests.Session() as session:
            while cursor > lo:
                for attempt in range(6):
                    with lock:
                        wait = max(0., next_request[0] - time.monotonic())
                        if wait:
                            time.sleep(wait)
                        next_request[0] = time.monotonic() + .21
                        requests_count[0] += 1
                    try:
                        response = session.get(ENDPOINT, params=dict(instId='BTC-USDT-SWAP',
                            bar='1m', limit='300', after=str(cursor)), timeout=30)
                        response.raise_for_status()
                        payload = response.json()
                        if payload.get('code') != '0':
                            raise ValueError(f"OKX returned code {payload.get('code')}")
                        page = payload['data']
                        if not page:
                            raise ValueError('empty page before requested history boundary')
                        break
                    except (requests.RequestException, ValueError):
                        if attempt == 5:
                            raise
                        time.sleep(min(2 ** attempt, 15))
                oldest = min(int(row[0]) for row in page)
                if oldest >= cursor:
                    raise ValueError('pagination did not advance')
                for row in page:
                    ts = int(row[0])
                    if lo <= ts < hi:
                        if row[8] != '1':
                            raise ValueError(f'unconfirmed candle {ts}')
                        normalized = [ts] + [float(v) for v in row[1:6]]
                        if ts in found and found[ts] != normalized:
                            raise ValueError('conflicting duplicate candle')
                        found[ts] = normalized
                cursor = oldest
        print(f'Fetched {utc(lo)} to {utc(hi)}: {len(found)} candles', flush=True)
        return found

    # Independent weekly windows; shared limiter stays below the documented limit.
    week = 7 * 24 * 60 * 60000
    windows = [(lo, min(lo + week, end)) for lo in range(start, end, week)]
    combined = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found in pool.map(fetch_window, windows):
            combined.update(found)
    expected = range(start, end, 60000)
    missing = [ts for ts in expected if ts not in combined]
    if missing:
        raise ValueError(f'{len(missing)} missing minutes; first {utc(missing[0])}; no data written')
    rows = [combined[ts] for ts in expected]
    normalize_ohlcv(rows)
    data = (json.dumps(rows, separators=(',', ':'), allow_nan=False) + '\n').encode()
    metadata = dict(exchange='OKX', instrument='BTC-USDT-SWAP', timeframe='1m',
        endpoint=ENDPOINT, start_utc=utc(start), end_exclusive_utc=utc(end), candles=len(rows),
        confirmed_only=True, missing_minutes=0, volume_unit='contracts',
        retrieved_utc=datetime.now(timezone.utc).isoformat(), requests=requests_count[0],
        sha256=hashlib.sha256(data).hexdigest())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    manifest.write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Saved {len(rows)} verified consecutive candles: {output}', flush=True)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    download(parse_utc(args.start), parse_utc(args.end), args.output)
