import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from typing import Any, Dict

import ccxt


def detect_resume(last_wall_ts: float, expected_sleep: int, grace_seconds: int = 10) -> tuple[bool, int]:
    """Detecta si hubo suspensión por un salto grande de reloj de pared.

    Retorna (resumed, drift_seconds), donde drift_seconds es cuánto excedió
    el tiempo esperado del ciclo.
    """
    now = time.time()
    elapsed = max(0, int(now - last_wall_ts))
    threshold = max(expected_sleep + grace_seconds, expected_sleep * 2)
    drift = elapsed - expected_sleep
    return elapsed >= threshold, max(0, drift)


def setup_logger(log_file: str, debug: bool = False) -> logging.Logger:
    """Configura un logger para consola y archivo."""
    lvl = logging.DEBUG if debug else logging.INFO
    logger = logging.getLogger("razr")
    logger.setLevel(lvl)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(lvl)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


from config import ConfigError, load_config


def validate_exchange(exchange, config):
    if not exchange.has.get("fetchOHLCV"):
        raise ConfigError("OKX does not report fetchOHLCV support")
    market = exchange.markets.get(config.symbol)
    if not market or not market.get("spot") or market.get("active") is False:
        raise ConfigError("configured market must exist and be active spot")
    if config.timeframe not in (exchange.timeframes or {}):
        raise ConfigError("configured timeframe is unsupported by OKX")
    if not 5 * config.macd_slow + config.macd_signal + 2 <= config.limit <= 300:
        raise ConfigError("history limit is outside the supported OKX candle range")


def connect_okx(config, logger) -> ccxt.Exchange:
    params = {"enableRateLimit": True, "timeout": 30000,
              "options": {"defaultType": "spot", "fetchMarkets": {"types": ["spot"]}}}
    if config.authenticated:
        params.update(apiKey=config.api_key, secret=config.api_secret, password=config.api_passphrase)
    logger.info("Connecting to OKX (%s data)", "authenticated" if config.authenticated else "public")
    exchange = ccxt.okx(params)
    try:
        exchange.load_markets()
        validate_exchange(exchange, config)
    except Exception as exc:
        if isinstance(exc, ccxt.OperationFailed):
            from runtime import retry_after
            exc.retry_after_seconds = retry_after(exchange, config.retry_max_seconds)
        close_exchange(exchange)
        raise
    logger.info("OKX spot metadata validated")
    return exchange


def safe_sleep(seconds: int, logger: logging.Logger):
    """Duerme un tiempo y permite limpieza de logs."""
    logger.debug(f"Durmiendo {seconds} segundos...")
    time.sleep(seconds)


def reconnect_exchange(config: Dict[str, Any], logger: logging.Logger) -> ccxt.Exchange:
    """Reconecta al exchange para limpiar estado de sockets tras suspensión."""
    logger.info("Reiniciando conexión con el exchange...")
    return connect_okx(config, logger)


def fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int, logger: logging.Logger):
    """Fetch public candles; callers log sanitized error categories."""
    return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def close_exchange(exchange):
    close = getattr(exchange, 'close', None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def build_dataframe(ohlcv):
    from market_data import normalize_ohlcv
    return normalize_ohlcv(ohlcv)


def fetch_current_price(exchange: ccxt.Exchange, symbol: str, logger: logging.Logger):
    """Obtiene precio actual de ticker sin necesidad de login."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker.get("last") or ticker.get("close") or ticker.get("lastPrice")
    except Exception as e:
        logger.warning(f"No se pudo obtener ticker actual: {e}")
        return None

