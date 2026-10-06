import math
import pandas as pd


def compute_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Calcula MACD + signal + histograma usando pandas."""

    if any(type(period) is not int or period <= 0 for period in (fast, slow, signal)) or fast >= slow:
        raise ValueError('MACD periods must be positive integers with fast < slow')
    if any(not math.isfinite(value) or value <= 0 for value in df['close']):
        raise ValueError('MACD closes must be finite positive numbers')
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line

    df["MACD"] = macd
    df["MACD_Signal"] = signal_line
    df["MACD_Hist"] = hist
    from signals import warmup
    df["eligible"] = [i >= warmup(fast, slow, signal) for i in range(len(df))]
    return df


def detect_macd_signal(df: pd.DataFrame):
    """Detecta cruce MACD/Signal y devuelve señal BUY/SELL o None."""
    if df.shape[0] < 2:
        return None

    if "eligible" in df and not df.eligible.iloc[-1]:
        return None
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    if any(not math.isfinite(row[key]) for row in (prev, curr)
           for key in ('MACD', 'MACD_Signal', 'MACD_Hist', 'close')):
        return None

    buy_cross = (prev["MACD"] <= prev["MACD_Signal"]) and (curr["MACD"] > curr["MACD_Signal"])
    sell_cross = (prev["MACD"] >= prev["MACD_Signal"]) and (curr["MACD"] < curr["MACD_Signal"])

    if curr["MACD"] <= 0 and (buy_cross or sell_cross):
        return {"signal": "BUY" if buy_cross else "SELL", "price": curr["close"], "macd": curr["MACD"], "signal_line": curr["MACD_Signal"], "hist": curr["MACD_Hist"], "timestamp": curr.name}

    return None


def signal_audit(events):
    """Count confirmed events; this audit is not a trade performance backtest."""
    return {
        "events": len(events),
        "buy_signals": sum(event["signal"] == "BUY" for event in events),
        "sell_signals": sum(event["signal"] == "SELL" for event in events),
        "last_signal": events[-1]["signal"] if events else "NONE",
    }
