# Deterministic signal fixture

`ohlcv.json` contains 240 **synthetic** consecutive one-minute candles starting
2026-01-01 00:00 UTC. It is not fetched OKX data and must not be presented as a
market-performance result. Opens are 100, highs 120, lows 80, volume 10; closes
are `round(100 + 10 * sin(i / 4), 10)` for candle index i. Values are committed
explicitly so replay does not depend on generating fresh floating-point inputs.

`events.json` stores eight default 12/26/9 MACD crossings after 139 warm-up
candles: indices 151 BUY, 163 SELL, 176 BUY, 188 SELL, 201 BUY, 213 SELL,
226 BUY, and 239 SELL. Indicator values were checked against the separate pandas
`ewm(adjust=False)` batch calculation. Replay uses the incremental production
state processor; tests compare direction, timestamp and numerical values.
Existing rational-number fixtures additionally verify the seeding convention.

The last SELL has no following candle in this sample, so it cannot execute in
the optional next-open simulation. The example evaluation split at 03:00 UTC
reserves 180 development candles and 60 evaluation candles. It is an example
split, not evidence of a tuned or profitable strategy.
