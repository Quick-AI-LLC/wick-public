#!/usr/bin/env python3
"""Offline checks — no RPC."""
import json, sys
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from metric.delta import delta_between, display_usdc, row_admitted
from metric.ohlc import build_candles

def parse_ts(s):
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()

def main():
    rows = [json.loads(l) for l in (HERE / "fixtures" / "ARGUS__v3__1%.sample.jsonl").read_text().splitlines() if l.strip()]
    assert rows[-1]["reserve_read_status"] == "reader_error"
    assert not row_admitted(rows[-1]), "dead row must not admit"
    assert display_usdc(rows[-1]["usdc_reserve_raw"], rows[-1]["usdc_dec"]) is None
    d = delta_between(rows[0], rows[1])
    assert d is not None and d < 0, d
    d_dead = delta_between(rows[-2], rows[-1])
    assert d_dead is None, d_dead
    series = [{"ts": parse_ts(r["ts"]), "price": r["price_usdc_per_token"]} for r in rows if r["price_usdc_per_token"] is not None]
    candles = build_candles(series, 3600)
    assert candles, "expected at least one 1H candle"
    c0 = candles[0]
    assert c0["n"] >= 1
    assert c0["h"] >= c0["l"]
    print(f"ok  rows={len(rows)}  first_delta={d}  1H_candles={len(candles)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
