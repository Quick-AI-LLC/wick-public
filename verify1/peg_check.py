"""
Pool-key helpers used by the snapshotter.

Keeps the production constants and the normalize() used to turn a config
row into a ReservesLens PoolKey. Representation (native 18-dec vs ERC-20
6-dec) is derived from the pool's own currencies, not trusted from a flag.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
LENS = "0x0000001b173C3bbF3984D417d8614E3eed34865B"
STATEVIEW = "0xF3334192D15450CdD385c8B70e03f9A6bD9E673b"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
USDC_ERC20 = "0x3600000000000000000000000000000000000000"


def _get(e: dict, *names, default=None):
    for n in names:
        if n in e and e[n] is not None:
            return e[n]
    return default


def _fee_to_uint24(e: dict, is_v4: bool) -> int:
    if not is_v4:
        return 0
    raw = _get(e, "fee", default="0")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw * 10000)
    s = str(raw).strip().lower()
    if s in ("dyn", "dynamic"):
        return 0x800000
    s = s.replace("%", "").strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        return 0
    return int((d * 10000).to_integral_value())


def derive_usdc_side(key: dict, erc20_usdc: str | None) -> tuple[int, bool] | None:
    c0, c1 = key["currency0"].lower(), key["currency1"].lower()
    erc20_usdc = erc20_usdc.lower() if isinstance(erc20_usdc, str) else None
    if c0 == ZERO_ADDR and c1 == ZERO_ADDR:
        return None
    if c0 == ZERO_ADDR:
        return 0, True
    if c1 == ZERO_ADDR:
        return 1, True
    if erc20_usdc:
        if c0 == erc20_usdc:
            return 0, False
        if c1 == erc20_usdc:
            return 1, False
    return None


def normalize(e: dict, idx: int, erc20_usdc: str | None = USDC_ERC20) -> dict | None:
    is_v4 = "tickSpacing" in e and "hooks" in e
    if not is_v4:
        token_ca = _get(e, "token_ca", "token", default=None)
        addr = _get(e, "lp_or_poolid", "address", "pool", default=None)
        if token_ca is None or addr is None:
            return None
        return {
            "pool_id": str(addr).lower(),
            "symbol": _get(e, "symbol", default="?"),
            "is_v4": False,
            "vanilla": True,
            "hooks": ZERO_ADDR,
            "token_ca": str(token_ca).lower(),
            "address": str(addr).lower(),
        }

    cur0 = _get(e, "currency0", "c0")
    cur1 = _get(e, "currency1", "c1")
    usdc_dec = _get(e, "usdc_dec", "usdc_decimals")
    if cur0 is None or cur1 is None or usdc_dec is None:
        return None
    cfg_side = _get(e, "usdc_side")
    if isinstance(cfg_side, str):
        s = cfg_side.strip().lower()
        cfg_side = 0 if s in ("c0", "0") else 1 if s in ("c1", "1") else None
    cfg_side = int(cfg_side) if cfg_side is not None else None

    derived = derive_usdc_side({"currency0": cur0, "currency1": cur1}, erc20_usdc)
    if derived is not None:
        usdc_side, quote_native = derived
    elif cfg_side is not None:
        usdc_side = cfg_side
        quote_native = (cur0 if usdc_side == 0 else cur1).lower() == ZERO_ADDR
    else:
        return None

    return {
        "pool_id": str(_get(e, "pool_id", "lp_or_poolid", default=f"idx{idx}")).lower(),
        "symbol": _get(e, "symbol", default="?"),
        "is_v4": True,
        "quote_native": quote_native,
        "usdc_side": usdc_side,
        "config_usdc_side": cfg_side,
        "usdc_dec": int(usdc_dec),
        "hooks": str(_get(e, "hooks", default=ZERO_ADDR)).lower(),
        "vanilla": str(_get(e, "hooks", default=ZERO_ADDR)).lower() == ZERO_ADDR,
        "key": {
            "currency0": cur0,
            "currency1": cur1,
            "fee": _fee_to_uint24(e, True),
            "tickSpacing": int(e["tickSpacing"]),
            "hooks": e["hooks"],
        },
    }
