"""15-minute price samples -> timeframe OHLC.

A 1H candle is four 15m prices: open = first, high = max, low = min, close = last.
High/low are sampled extremes. An intra-interval tick that we did not snapshot
does not exist in this dataset. Empty buckets are skipped — never fabricated.
"""
from __future__ import annotations

TIMEFRAMES = {
    "1H": 3600,
    "4H": 4 * 3600,
    "1D": 86400,
    "1W": 7 * 86400,
}


def build_candles(series, tf_sec=3600):
    """series: iterable of {ts, price}. ts is unix seconds.
    Returns [{t, o, h, l, c, n}] aligned to epoch multiples of tf_sec.
    """
    out = []
    cur = None
    for p in series:
        price = p["price"]
        if price is None:
            continue
        t = int(p["ts"] // tf_sec) * tf_sec
        if cur is None or cur["t"] != t:
            if cur:
                out.append(cur)
            cur = {"t": t, "o": price, "h": price, "l": price, "c": price, "n": 1}
        else:
            cur["h"] = max(cur["h"], price)
            cur["l"] = min(cur["l"], price)
            cur["c"] = price
            cur["n"] += 1
    if cur:
        out.append(cur)
    return out
