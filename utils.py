import logging
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
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(lvl)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


def load_config(path: str) -> Dict[str, Any]:
    """Carga configuración YAML."""
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def connect_okx(config: Dict[str, Any], logger: logging.Logger) -> ccxt.Exchange:
    """Conecta a OKX con CCXT y retorna el exchange. Puede funcionar solo para datos públicos."""
    api_key = config.get("api_key")
    api_secret = config.get("api_secret")
    passphrase = config.get("api_passphrase", "")

    exchange_id = config.get("exchange", "okx").lower()
    if exchange_id not in ccxt.exchanges:
        raise ValueError(f"Exchange desconocido: {exchange_id}")

    exchange_class = getattr(ccxt, exchange_id)
    params = {
        "enableRateLimit": True,
        "rateLimit": 1000,
        "timeout": 30000,
    }
    if api_key and api_secret:
        params["apiKey"] = api_key
        params["secret"] = api_secret
        params["password"] = passphrase
    else:
        logger.warning("No se encontraron API keys; usando solo endpoints públicos.")

    exchange = exchange_class(params)

    # Ajustes para network y proxies opcionales
    exchange.options = {
        **exchange.options,
        "adjustForTimeDifference": True,
    }

    logger.info("Conectando a OKX...")
    try:
        exchange.load_markets()
    except Exception as exc:
        logger.error(f"Error cargando mercados OKX: {exc}")
        raise
    logger.info("Conexión OKX establecida")
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
    """Descarga velas OHLCV."""
    try:
        market = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except ccxt.NetworkError as e:
        logger.warning(f"Network error fetch_ohlcv: {e}")
        raise
    except ccxt.RateLimitExceeded as e:
        logger.warning(f"Rate limit exceeded: {e}")
        raise
    except Exception as e:
        logger.error(f"Error inesperado fetch_ohlcv: {e}")
        raise
    return market


def build_dataframe(ohlcv):
    """Construye DataFrame pandas de OHLCV."""
    import pandas as pd

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)
    return df


def fetch_current_price(exchange: ccxt.Exchange, symbol: str, logger: logging.Logger):
    """Obtiene precio actual de ticker sin necesidad de login."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker.get("last") or ticker.get("close") or ticker.get("lastPrice")
    except Exception as e:
        logger.warning(f"No se pudo obtener ticker actual: {e}")
        return None

