import sys
import traceback
from datetime import datetime

from colorama import Fore, Style

from alerts import play_sound, send_desktop_alert
from indicators import backtest_signals, compute_macd, detect_macd_signal
from utils import (build_dataframe, connect_okx, fetch_current_price, fetch_ohlcv, load_config,
                   safe_sleep, setup_logger)


def format_signal_message(signal_data: dict, symbol: str, timeframe: str):
    """Formatea mensaje para alerta de escritorio y log."""
    ts = signal_data["timestamp"]
    if hasattr(ts, "strftime"):
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    else:
        ts_str = str(ts)

    title = f"🚨 MACD SIGNAL - {signal_data['signal']}"
    body = (
        f"{symbol} {timeframe}\n"
        f"Precio: {signal_data['price']:.2f}\n"
        f"MACD: {signal_data['macd']:.6f}\n"
        f"Signal: {signal_data['signal_line']:.6f}\n"
        f"Hist: {signal_data['hist']:.6f}\n"
        f"Fuerte: {'Sí' if signal_data['strong'] else 'No'}\n"
        f"TS: {ts_str}"
    )
    return title, body


def print_colored(signal_data: dict):
    """Imprime en consola con colores."""
    if signal_data["signal"] == "BUY":
        c = Fore.GREEN
    else:
        c = Fore.RED
    print(
        f"{c}{datetime.now():%Y-%m-%d %H:%M:%S} - {signal_data['signal']} - Precio {signal_data['price']:.2f} - MACD {signal_data['macd']:.6f} - Signal {signal_data['signal_line']:.6f} - Hist {signal_data['hist']:.6f}{Style.RESET_ALL}"
    )


def main():
    config = load_config("config.yaml")
    debug = config.get("debug", False)
    logger = setup_logger("razr.log", debug=debug)

    symbol = config.get("symbol", "BTC/USDT")
    timeframe = config.get("timeframe", "15m")
    macd_fast = int(config.get("macd_fast", 12))
    macd_slow = int(config.get("macd_slow", 26))
    macd_signal = int(config.get("macd_signal", 9))
    limit = int(config.get("limit", 200))
    sleep_seconds = int(config.get("sleep_seconds", 30))
    sound_file = config.get("sound_file")
    urgency = config.get("notify_urgency", "critical")

    exchange = connect_okx(config, logger)
    last_signal = None

    logger.info("Iniciando bucle principal de razr...")
    logger.info(f"Símbolo: {symbol}, timeframe: {timeframe}, MACD: {macd_fast},{macd_slow},{macd_signal}")

    while True:
        try:
            ohlcv = fetch_ohlcv(exchange, symbol, timeframe, limit, logger)
            df = build_dataframe(ohlcv)
            df = compute_macd(df, fast=macd_fast, slow=macd_slow, signal=macd_signal)

            signal = detect_macd_signal(df)
            bt = backtest_signals(df)
            logger.debug(f"Backtest señales: {bt}")
            current_price = fetch_current_price(exchange, symbol, logger)
            if current_price is not None:
                logger.debug(f"Precio de ticker actual (sin login): {current_price}")

            if signal is not None:
                if last_signal != signal["signal"]:
                    title, body = format_signal_message(signal, symbol, timeframe)
                    logger.warning(f"ALERTA {signal['signal']}: precio {signal['price']:.2f} hist {signal['hist']:.6f}")
                    logger.warning(body.replace('\n', ' | '))
                    print_colored(signal)
                    try:
                        send_desktop_alert(title, body, urgency)
                    except Exception as e:
                        logger.error(f"Fallo al enviar notificación: {e}")

                    try:
                        play_sound(sound_file)
                    except Exception as e:
                        logger.error(f"Fallo al reproducir sonido: {e}")

                    last_signal = signal["signal"]
                else:
                    logger.debug("Señal detectada igual a la última; no se repite alerta.")
            else:
                logger.debug("No hay señal MACD en este ciclo.")

            safe_sleep(sleep_seconds, logger)

        except KeyboardInterrupt:
            logger.info("Interrumpido por usuario. Saliendo...")
            sys.exit(0)
        except Exception as exc:
            trace = traceback.format_exc()
            logger.error(f"Error en main loop: {exc}\n{trace}")
            logger.info("Esperando 30s antes de reintentar...")
            safe_sleep(30, logger)


if __name__ == "__main__":
    main()
