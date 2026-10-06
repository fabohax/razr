import sys
import argparse
import time

import ccxt

from config import ConfigError, application_paths, load_config, initialize_config
from alerts import play_sound, send_desktop_alert, capability, UnavailableChannel
from market_data import closed_candles, DataError
from signals import process
from state import State, namespace
import json
from utils import connect_okx, fetch_ohlcv, setup_logger, close_exchange
from runtime import RunnerLock, Stop, RetryClock, backoff, retry_after, resumed
from signals import utc
from pathlib import Path
import os
import uuid
from operator_state import write_json


def format_signal_message(signal_data: dict, symbol: str, timeframe: str):
    """Formatea mensaje para alerta de escritorio y log."""
    title = f"MACD {signal_data['signal']} — {signal_data['exchange']} spot"
    body = (
        f"{symbol} {timeframe} {signal_data['signal']}\n"
        f"Open: {signal_data['open_utc']}\nClose: {signal_data['close_utc']}\n"
        f"Candle close price: {signal_data['price']:.2f}\n"
        f"MACD: {signal_data['macd']:.8f} Signal: {signal_data['signal_line']:.8f} Hist: {signal_data['hist']:.8f}\n"
        f"Strategy: {signal_data['strategy_version']} {signal_data['parameters']}\n"
        f"Recovered: {signal_data['recovered']}\nEvent ID: {signal_data['event_id']}"
    )
    return title, body


def channel_enabled(channel, config, args):
    if channel not in ('desktop', 'sound'):
        return True
    return (config.notifications and not args.no_notifications and
            ((channel == 'desktop' and config.desktop_notifications) or
             (channel == 'sound' and config.sound_notifications)))


def deliver_pending(state, config, args, logger, sound_file, clock=None, stop=None):
    now = clock.now() if clock else time.time()
    for payload, channel in state.pending(due_at=now):
        if stop and stop.stopped():
            break
        event = json.loads(payload)
        age = time.time() * 1000 - event['candle_ms'] - 60000
        if age > config.alert_age_limit_seconds * 1000:
            state.delivered(event['event_id'], channel, 'expired')
            continue
        if not channel_enabled(channel, config, args):
            continue
        title, body = format_signal_message(event, event['symbol'], event['timeframe'])
        try:
            if channel == 'console_log':
                logger.warning('%s | %s', title, body.replace('\n', ' | '))
            elif channel == 'desktop':
                send_desktop_alert(title, body, config.notify_urgency)
            elif channel == 'sound':
                play_sound(sound_file)
            else:
                raise UnavailableChannel('unknown delivery channel')
            state.delivered(event['event_id'], channel)
        except Exception as exc:
            count = state.retry_count(event['event_id'], channel) + 1
            delay = backoff(count, config.retry_base_seconds, config.retry_max_seconds)
            # Persist categories, never exception strings which may contain secrets.
            state.failed_attempt(event['event_id'], channel, type(exc).__name__, now,
                                 delay, config.delivery_max_attempts,
                                 permanent=isinstance(exc, UnavailableChannel))
            logger.error('Delivery failed event=%s channel=%s attempt=%s error=%s retry_in=%.1fs',
                         event['event_id'], channel, count, type(exc).__name__, delay)


def report_health(state, config, logger, last_fetch, last_close, status, failures, poll_at, paths=None, session_id=None):
    cp = state.checkpoint(namespace(config))
    counts, due = state.health()
    known_close = last_close if last_close is not None else (cp[0] + 60000 if cp else None)
    lag = None if known_close is None else round(time.time() - known_close / 1000, 1)
    logger.info('Health status=%s last_fetch=%s last_processed_close=%s data_lag_seconds=%s '
                'pending=%s failed=%s next_delivery_retry_utc=%s network_attempt=%s next_poll_in=%.1fs',
                status, utc(last_fetch * 1000) if last_fetch is not None else 'never',
                utc(cp[0] + 60000) if cp else 'never', lag,
                counts.get('pending', 0), counts.get('failed', 0),
                utc(due * 1000) if due is not None else 'none', failures,
                max(0, poll_at - time.monotonic()))
    if paths is not None:
        record = dict(status=status, last_fetch_utc=utc(last_fetch*1000) if last_fetch is not None else None,
                      last_candle_utc=utc(cp[0]+60000) if cp else None,
                      data_lag_seconds=lag, pending=counts.get('pending',0), failed=counts.get('failed',0),
                      network_attempt=failures, next_poll_seconds=max(0,poll_at-time.monotonic()),
                      updated_at=time.time(), pid=os.getpid(), session_id=session_id)
        write_json(paths.directory/'health.json',record)



def run(config, paths, args, logger, stop):
    state = State(paths.state)
    if getattr(args, 'retry_failed', False):
        count = state.requeue_failed()
        logger.info('Requeued %s failed delivery jobs', count)
    exchange = None
    clock = RetryClock()
    sound_file = config.sound_file
    if sound_file:
        path = Path(sound_file).expanduser()
        sound_file = str(path if path.is_absolute() else paths.directory / path)
    channels = [channel for channel in ('console_log', 'desktop', 'sound')
                if channel_enabled(channel, config, args)]
    for channel in channels:
        reason = capability(channel, sound_file)
        if reason:
            logger.warning('Channel %s unavailable: %s; delivery jobs will record failure', channel, reason)
    poll_at = health_at = time.monotonic()
    previous_wall, previous_mono = time.time(), time.monotonic()
    failures = 0
    last_fetch = last_close = None
    status = 'starting'
    session_id = getattr(args, 'session_id', None)
    deadline = time.monotonic()+args.run_for_seconds if getattr(args,'run_for_seconds',None) else None
    try:
        report_health(state,config,logger,last_fetch,last_close,status,failures,poll_at,paths,session_id)
        while not stop.stopped():
            if getattr(args, "stop_at_epoch", None) is not None and time.time() >= args.stop_at_epoch:
                logger.info("Soak UTC deadline reached")
                break
            if deadline is not None and time.monotonic() >= deadline:
                logger.info('Scheduled run duration reached')
                break
            now = time.monotonic()
            if resumed(previous_wall, previous_mono, config.resume_grace_seconds):
                logger.warning('Clock/suspend discontinuity detected; reconnecting and checking missed closes')
                close_exchange(exchange)
                exchange = None
                last_close = None
                clock = RetryClock()
                poll_at = now
                status = 'recovering'
            previous_wall, previous_mono = time.time(), now
            if now >= poll_at:
                try:
                    if exchange is None:
                        exchange = connect_okx(config, logger)
                    if stop.stopped():
                        break
                    if getattr(args,'soak',False):
                        try:
                            offline = json.loads((paths.directory/'offline-test.json').read_text())
                        except (OSError,ValueError):
                            offline = {}
                        if time.time() < offline.get('until',0):
                            logger.warning('Controlled soak fetch outage active')
                            raise ccxt.NetworkError('controlled fetch outage')
                    rows = fetch_ohlcv(exchange, config.symbol, config.timeframe, config.limit, logger)
                    last_fetch = time.time()
                    if stop.stopped():
                        break
                    df = closed_candles(rows, last_fetch * 1000, config.close_grace_seconds,
                                        config.stale_after_seconds)
                    events = process(df, config, state, last_fetch * 1000, channels)
                    last_close = int(df.timestamp.iloc[-1]) + 60000
                    logger.info('Data cycle complete: %s closed candles, %s new events', len(df), len(events))
                    failures = 0
                    status = 'healthy'
                    poll_at = time.monotonic() + config.sleep_seconds
                except (ConfigError, ccxt.ExchangeError) as exc:
                    status = 'failed'
                    report_health(state,config,logger,last_fetch,last_close,status,failures,poll_at,paths,session_id)
                    logger.error('Configuration/exchange error (%s); correct settings before restarting', type(exc).__name__)
                    return 2
                except ccxt.OperationFailed as exc:
                    failures += 1
                    delay = backoff(failures, config.retry_base_seconds, config.retry_max_seconds,
                                    max(retry_after(exchange, config.retry_max_seconds),
                                        getattr(exc, 'retry_after_seconds', 0)))
                    logger.warning('Network/API failure (%s), attempt=%s retry_in=%.1fs',
                                   type(exc).__name__, failures, delay)
                    status = 'retrying'
                    poll_at = time.monotonic() + delay
                    # Keep CCXT's rate-limiter and headers for rate-limit retries.
                    if not isinstance(exc, ccxt.RateLimitExceeded):
                        close_exchange(exchange)
                        exchange = None
                    if args.once:
                        report_health(state,config,logger,last_fetch,last_close,status,failures,poll_at,paths,session_id)
                        return 1
                except DataError as exc:
                    logger.error('Data rejected: %s', exc)  # locally generated, no exchange payload
                    last_close = None
                    status = 'stale' if 'stale' in str(exc) else 'data_error'
                    poll_at = time.monotonic() + config.sleep_seconds
                    if args.once:
                        report_health(state,config,logger,last_fetch,last_close,status,failures,poll_at,paths,session_id)
                        return 1
                report_health(state, config, logger, last_fetch, last_close, status, failures, poll_at, paths, session_id)
                # Queue dispatch runs separately from the fetch schedule. Stale or
                # unresolved input blocks sending until a valid cycle succeeds.
                if args.once:
                    deliver_pending(state, config, args, logger, sound_file, clock, stop)
                    report_health(state, config, logger, last_fetch, last_close, status, failures, poll_at, paths, session_id)
                    return 0
            fresh = last_close is not None and time.time() - last_close / 1000 <= config.stale_after_seconds
            if fresh:
                deliver_pending(state, config, args, logger, sound_file, clock, stop)
            elif status == 'healthy':
                status = 'stale'
            if time.monotonic() >= health_at:
                report_health(state, config, logger, last_fetch, last_close, status, failures, poll_at, paths, session_id)
                health_at = time.monotonic() + config.health_interval_seconds
            if stop.stopped():
                break
            stop.wait(min(1, max(0, poll_at - time.monotonic()),
                          max(0, health_at - time.monotonic())))
        return 0
    finally:
        close_exchange(exchange)
        try:
            report_health(state,config,logger,last_fetch,last_close,'stopped' if status != 'failed' else 'failed',failures,poll_at,paths,session_id)
        finally:
            state.close()
        logger.info('Runner stopped; state closed')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Razr public OKX spot MACD monitor')
    parser.add_argument('--soak',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--stop-at-epoch',type=float,help=argparse.SUPPRESS)
    parser.add_argument('--init-config', action='store_true', help='create public default config if missing')
    parser.add_argument('--test-alert', action='store_true', help='test enabled local channels without exchange access')
    parser.add_argument('--session-id', default=None, help=argparse.SUPPRESS)
    parser.add_argument('--run-for-seconds', type=int, help='stop after a bounded monitoring run')
    parser.add_argument('--app-dir', help='writable directory for config, logs and state')
    parser.add_argument('--config', help='explicit YAML path (default: APP_DIR/config.yaml)')
    parser.add_argument('--check-config', action='store_true', help='validate settings without network')
    parser.add_argument('--once', action='store_true', help='one cycle, no network retries')
    parser.add_argument('--retry-failed', action='store_true', help='requeue failed delivery jobs with a fresh attempt budget')
    parser.add_argument('--no-notifications', action='store_true', help='disable desktop and sound')
    args = parser.parse_args(argv)
    try:
        paths = application_paths(args.app_dir, args.config)
        if args.init_config:
            created = initialize_config(paths)
            print(f'Configuration {"created" if created else "already exists"}: {paths.config}')
            if not args.check_config and not args.test_alert:
                return 0
        config = load_config(paths.config)
    except ConfigError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        return 2
    if args.check_config:
        print(f'Configuration valid: {paths.config}; application directory: {paths.directory}')
        return 0
    if args.run_for_seconds is not None and args.run_for_seconds <= 0:
        parser.error('--run-for-seconds must be positive')
    args.session_id = args.session_id or uuid.uuid4().hex
    logger = None
    try:
        # Acquire before replacing logger handlers or touching the database.
        with RunnerLock(paths.directory / 'runner.lock'), Stop() as stop:
            logger = setup_logger(str(paths.log), debug=config.debug)
            if args.test_alert:
                failures = 0
                logger.info('Razr TEST ALERT: public spot monitor; no trade signal')
                sound_file = config.sound_file
                if sound_file:
                    sound = Path(sound_file).expanduser()
                    sound_file = str(sound if sound.is_absolute() else paths.directory / sound)
                for channel in ('desktop','sound'):
                    if not channel_enabled(channel,config,args):
                        continue
                    try:
                        if channel=='desktop':
                            send_desktop_alert('Razr TEST ALERT','Test only — not a trading signal',config.notify_urgency)
                        else:
                            play_sound(sound_file)
                        logger.info('Test channel %s delivered',channel)
                    except Exception as exc:
                        failures += 1
                        logger.error('Test channel %s failed (%s)',channel,type(exc).__name__)
                return 1 if failures else 0
            return run(config, paths, args, logger, stop)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Avoid logging raw library errors, response bodies or private configuration.
        message = 'another runner is using this application directory' if isinstance(exc, RuntimeError) and 'another runner' in str(exc) else type(exc).__name__
        if logger:
            logger.error('Runner failed: %s', message)
        else:
            print(f'Startup error: {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
