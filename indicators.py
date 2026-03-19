import pandas as pd


def compute_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Calcula MACD + signal + histograma usando pandas_ta."""
    import pandas_ta as ta

    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line

    df["MACD"] = macd
    df["MACD_Signal"] = signal_line
    df["MACD_Hist"] = hist
    return df


def detect_macd_signal(df: pd.DataFrame):
    """Detecta cruce MACD/Signal y devuelve señal BUY/SELL o None."""
    if df.shape[0] < 2:
        return None

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    buy_cross = (prev["MACD"] <= prev["MACD_Signal"]) and (curr["MACD"] > curr["MACD_Signal"])
    sell_cross = (prev["MACD"] >= prev["MACD_Signal"]) and (curr["MACD"] < curr["MACD_Signal"])

    if buy_cross:
        note = "BUY"
        strong = curr["MACD_Hist"] > 0
        return {"signal": "BUY", "strong": strong, "price": curr["close"], "macd": curr["MACD"], "signal_line": curr["MACD_Signal"], "hist": curr["MACD_Hist"], "timestamp": curr.name}
    if sell_cross:
        strong = curr["MACD_Hist"] < 0
        return {"signal": "SELL", "strong": strong, "price": curr["close"], "macd": curr["MACD"], "signal_line": curr["MACD_Signal"], "hist": curr["MACD_Hist"], "timestamp": curr.name}

    return None


def backtest_signals(df: pd.DataFrame):
    """Backtest simple de cruces para auditoria.
    Devuelve un dict con conteos de señales y últimos cruces."""
    df = df.copy()
    df["prev_macd"] = df["MACD"].shift(1)
    df["prev_signal"] = df["MACD_Signal"].shift(1)

    df["buy_cross"] = (df["prev_macd"] <= df["prev_signal"]) & (df["MACD"] > df["MACD_Signal"])
    df["sell_cross"] = (df["prev_macd"] >= df["prev_signal"]) & (df["MACD"] < df["MACD_Signal"])

    buys = int(df["buy_cross"].sum())
    sells = int(df["sell_cross"].sum())
    total = df.shape[0]

    return {
        "candles": total,
        "buy_signals": buys,
        "sell_signals": sells,
        "last_signal": "BUY" if df["buy_cross"].iloc[-1] else "SELL" if df["sell_cross"].iloc[-1] else "NONE",
    }
