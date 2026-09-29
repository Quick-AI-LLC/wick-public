#!/usr/bin/env python3
"""
Wick capture kit — read-only Arc mainnet snapshots of USDC pools.

  v3 : pair token0()/token1() at read time; quote is native-18 or USDC ERC-20-6
  v4 : StateView.getSlot0 for price; ReservesLens.getPoolTVL for reserves

One append-only JSONL file per pool. No signing. Deps: requests.

    WICK_CONFIG=config/founding-pools.public.json WICK_DATA=./out python3 snapshotter.py
"""
import json, os, sys, time, requests
from datetime import datetime, timezone
from decimal import Decimal, getcontext

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify1"))
try:
    from v4_reserve_reader import V4ReserveReader
    from peg_check import POOL_MANAGER, LENS, normalize as wick_normalize
    _V4_AVAIL = True
except Exception:
    _V4_AVAIL = False

HERE = os.path.dirname(os.path.abspath(__file__))
RPC          = os.environ.get("WICK_RPC", "https://rpc.mainnet.arc.io")
STATE_VIEW   = "0xF3334192D15450CdD385c8B70e03f9A6bD9E673b"
USDC_ERC20   = "0x3600000000000000000000000000000000000000"
ZERO_ADDR    = "0x0000000000000000000000000000000000000000"
CONF         = os.environ.get("WICK_CONFIG", os.path.join(HERE, "config", "founding-pools.public.json"))
DATA_DIR     = os.environ.get("WICK_DATA", os.path.join(HERE, "out"))
SEL_GET_SLOT0 = "0xc815641c"
SEL_DECIMALS  = "0x313ce567"
SEL_BALANCEOF = "0x70a08231"
SEL_TOKEN0    = "0x0dfe1681"
SEL_TOKEN1    = "0xd21220a7"
RPC_HEADERS   = {
    "Content-Type": "application/json",
    "User-Agent": "WickCapture/1.0 (+https://wick.green)",
}
RPC_RETRIES   = 3

getcontext().prec = 40


def rpc(method, params, rpc_url=RPC):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    last = None
    for attempt in range(RPC_RETRIES):
        try:
            r = requests.post(rpc_url, json=payload, headers=RPC_HEADERS, timeout=30)
            if r.status_code in (403, 429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(0.4 * (attempt + 1))
                continue
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"{method}: {d['error']}")
            return d["result"]
        except RuntimeError:
            raise
        except Exception as e:
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"{method}: exhausted retries ({last})")


def to_int(hex_str):
    return int(hex_str, 16)


def fmt_addr(addr):
    a = addr.lower()
    if a.startswith("0x"):
        a = a[2:]
    return a


def call_addr(to, sel):
    out = rpc("eth_call", [{"to": to, "data": sel}, "latest"])
    if not out or out == "0x":
        raise RuntimeError(f"{sel[:10]} empty on {to[:12]}")
    h = out[2:].rjust(64, "0")
    return ("0x" + h[-40:]).lower()


def slot0(pool_id):
    data = SEL_GET_SLOT0 + fmt_addr(pool_id).rjust(64, "0")
    out = rpc("eth_call", [{"to": STATE_VIEW, "data": data}, "latest"])
    if not out or out == "0x":
        raise RuntimeError("getSlot0 empty")
    h = out[2:]
    if len(h) < 128:
        raise RuntimeError(f"getSlot0 short ({len(h)}): {out[:80]}")
    sqrt = to_int(h[0:64])
    tick = to_int(h[64:128])
    fee_word = to_int(h[192:256]) if len(h) >= 256 else None
    if tick >= 1 << 23:
        tick -= 1 << 24
    return sqrt, tick, fee_word


def v3_read(lp, token_ca, dec_cache):
    token_ca = token_ca.lower()
    t0 = call_addr(lp, SEL_TOKEN0)
    t1 = call_addr(lp, SEL_TOKEN1)
    if t0 == token_ca:
        token_is_c0, quote = True, t1
    elif t1 == token_ca:
        token_is_c0, quote = False, t0
    else:
        raise RuntimeError(
            f"token_ca {token_ca[:12]} is neither token0 {t0[:12]} nor token1 {t1[:12]}"
        )
    if quote == ZERO_ADDR:
        usdc = to_int(rpc("eth_getBalance", [lp, "latest"]))
        usdc_dec, usdc_rep = 18, "native"
    elif quote == USDC_ERC20:
        usdc_dec = token_decimals(quote, dec_cache)
        if usdc_dec is None:
            raise RuntimeError(f"decimals() empty on quote {quote[:12]}")
        data = SEL_BALANCEOF + fmt_addr(lp).rjust(64, "0")
        usdc = to_int(rpc("eth_call", [{"to": quote, "data": data}, "latest"]))
        usdc_rep = "erc20"
    else:
        raise RuntimeError(
            f"quote {quote[:12]} is not native or USDC ERC-20 predeploy — refused"
        )
    tkn_data = SEL_BALANCEOF + fmt_addr(lp).rjust(64, "0")
    tkn = to_int(rpc("eth_call", [{"to": token_ca, "data": tkn_data}, "latest"]))
    return {
        "usdc_raw": usdc,
        "token_raw": tkn,
        "usdc_dec": int(usdc_dec),
        "usdc_representation": usdc_rep,
        "quote_addr": quote,
        "token_is_c0": token_is_c0,
        "token0": t0,
        "token1": t1,
    }


def price_usdc_per_token(version, usdc_reserve, token_reserve, tok_dec,
                         sqrt=None, token_is_c0=None, usdc_dec=18):
    if version == "v4":
        dec = tok_dec if tok_dec is not None else 18
        p = (Decimal(sqrt) / (Decimal(2) ** 96)) ** 2
        ratio = p if token_is_c0 else (Decimal(1) / p)
        return float(ratio * (Decimal(10) ** (dec - usdc_dec)))
    if not token_reserve or tok_dec is None:
        return None
    usdc = Decimal(usdc_reserve) / (Decimal(10) ** usdc_dec)
    tkn = Decimal(token_reserve) / (Decimal(10) ** tok_dec)
    return float(usdc / tkn) if tkn else None


def token_decimals(token, cache):
    if token in cache:
        return cache[token]
    try:
        out = rpc("eth_call", [{"to": token, "data": SEL_DECIMALS}, "latest"])
        d = to_int(out) if out and out != "0x" else None
    except Exception:
        d = None
    cache[token] = d
    return d


def pool_key(p):
    fee = ("DYN" if p["version"] == "v4" and not p.get("fee") else p.get("fee") or "0").replace(" ", "")
    return f"{p['symbol'].upper()}__{p['version']}__{fee}"


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONF) as f:
        cfg = json.load(f)
    pools = cfg["pools"]
    from collections import Counter
    key_count = Counter(pool_key(p) for p in pools)
    dec_cache = {}
    blk = to_int(rpc("eth_blockNumber", []))
    now = datetime.now(timezone.utc).isoformat()
    results = {"ok": 0, "err": 0}

    rdr, v4_norm = None, {}
    if _V4_AVAIL:
        try:
            for _i, _p in enumerate(pools):
                if _p.get("version") == "v4":
                    _n = wick_normalize(_p, _i)
                    if _n:
                        v4_norm[(_n["pool_id"] or "").lower()] = _n
            rdr = V4ReserveReader(RPC, POOL_MANAGER, LENS)
        except Exception:
            rdr = None

    for p in pools:
        key = pool_key(p)
        suffix = ("__" + str(p["lp_or_poolid"])[-4:]) if key_count[key] > 1 else ""
        fname = os.path.join(DATA_DIR, key + suffix + ".jsonl")
        tok_dec = token_decimals(p["token_ca"], dec_cache)
        try:
            if p["version"] == "v4":
                sqrt, tick, fee_word = slot0(p["lp_or_poolid"])
                token_is_c0 = p.get("token_is_c0", False)
                udec = p.get("usdc_dec", 18)
                price = price_usdc_per_token(
                    "v4", None, None, tok_dec, sqrt=sqrt, token_is_c0=token_is_c0, usdc_dec=udec
                )
                row = {
                    "ts": now, "block": blk, "symbol": p["symbol"], "pool": p.get("pool_label"),
                    "version": "v4", "fee": p.get("fee"), "token_ca": p["token_ca"],
                    "pool_id": p["lp_or_poolid"],
                    "sqrtPriceX96": str(sqrt), "tick": tick, "onchain_fee": fee_word,
                    "price_usdc_per_token": price, "token_decimals": tok_dec,
                    "usdc_dec": int(udec),
                    "usdc_representation": ("native" if int(udec) == 18 else "erc20"),
                    "hooks": p.get("hooks"),
                    "reserve_read_status": None,
                    "usdc_reserve_raw": None,
                    "token_reserve_raw": None,
                }
                if rdr is not None:
                    _n = v4_norm.get(p["lp_or_poolid"].lower())
                    if _n is not None:
                        row["usdc_side"] = int(_n["usdc_side"])
                        _cfg = dict(_n)
                        _cfg["fee"] = p.get("fee")
                        try:
                            _res = rdr.read(_n["key"])
                            row.update(_res.to_row_fragment(_cfg))
                            row["onchain_fee"] = fee_word if fee_word is not None else row.get("onchain_fee")
                        except Exception:
                            row["reserve_read_status"] = "reader_error"
            else:
                got = v3_read(p["lp_or_poolid"], p["token_ca"], dec_cache)
                price = price_usdc_per_token(
                    "v3", got["usdc_raw"], got["token_raw"], tok_dec, usdc_dec=got["usdc_dec"],
                )
                row = {
                    "ts": now, "block": blk, "symbol": p["symbol"], "pool": p.get("pool_label"),
                    "version": "v3", "fee": p.get("fee"), "token_ca": p["token_ca"],
                    "lp": p["lp_or_poolid"],
                    "usdc_reserve_raw": str(got["usdc_raw"]),
                    "token_reserve_raw": str(got["token_raw"]),
                    "price_usdc_per_token": price, "token_decimals": tok_dec,
                    "usdc_dec": got["usdc_dec"],
                    "usdc_representation": got["usdc_representation"],
                    "quote_addr": got["quote_addr"],
                    "token_is_c0": got["token_is_c0"],
                    "reserve_read_status": "green",
                }
            with open(fname, "a") as f:
                f.write(json.dumps(row) + "\n")
            results["ok"] += 1
        except Exception as e:
            results["err"] += 1
            print(f"ERR {p.get('pool_label')} {p['version']} {p.get('lp_or_poolid','')[:12]}: {e}", file=sys.stderr)
    print(f"block={blk} ok={results['ok']} err={results['err']} v4reserves={'on' if rdr is not None else 'off'}")
    return 0 if results["err"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
