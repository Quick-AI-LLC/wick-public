"""Keccak-256 + Uniswap/Arc selector anchors. Stdlib only."""
from __future__ import annotations

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_MASK = (1 << 64) - 1


def _rotl(v: int, n: int) -> int:
    n %= 64
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def _keccak_f(lanes: list) -> None:
    for rnd in range(24):
        c = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20]
             for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                lanes[x + 5 * y] ^= d[x]
        x, y = 1, 0
        current = lanes[x + 5 * y]
        for t in range(24):
            x, y = y, (2 * x + 3 * y) % 5
            idx = x + 5 * y
            current, lanes[idx] = lanes[idx], _rotl(current, ((t + 1) * (t + 2) // 2) % 64)
        b = lanes[:]
        for xx in range(5):
            for yy in range(5):
                lanes[xx + 5 * yy] = b[xx + 5 * yy] ^ (
                    (~b[(xx + 1) % 5 + 5 * yy]) & _MASK & b[(xx + 2) % 5 + 5 * yy]
                )
        lanes[0] ^= _RC[rnd]


def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data)
    pad_len = rate - (len(padded) % rate)
    padded += b"\x01" + b"\x00" * (pad_len - 2) + b"\x80" if pad_len >= 2 else b"\x81"
    st = [0] * 25
    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(block[i * 8:(i + 1) * 8], "little")
        _keccak_f(st)
    return b"".join(st[i].to_bytes(8, "little") for i in range(4))


def selector(sig: str) -> bytes:
    return keccak256(sig.encode("ascii"))[:4]


SIG_GET_POOL_TVL = "getPoolTVL(address,(address,address,uint24,int24,address))"
SIG_GET_POOL_TVL_PAGED = "getPoolTVLPaged(address,(address,address,uint24,int24,address),bytes)"
SIG_GET_POOL_TVL_PAGED5 = (
    "getPoolTVLPaged(address,(address,address,uint24,int24,address),address,bytes,uint32)"
)
SIG_GET_SLOT0 = "getSlot0(bytes32)"
SIG_GET_LIQUIDITY = "getLiquidity(bytes32)"
SIG_ERR_STRING = "Error(string)"
SIG_POOL_NOT_INITIALIZED = "PoolNotInitialized(bytes32)"

GROUND_TRUTH = {
    SIG_GET_POOL_TVL: "f95138f2",
    SIG_GET_SLOT0: "c815641c",
    SIG_GET_LIQUIDITY: "fa6793d5",
}


class SelectorDerivationMismatch(AssertionError):
    pass


def assert_selectors() -> dict:
    derived = {}
    for sig, expected_hex in GROUND_TRUTH.items():
        got = selector(sig).hex()
        if got != expected_hex:
            raise SelectorDerivationMismatch(
                f"derived {got} for {sig!r}, known anchor is {expected_hex}"
            )
        derived[sig] = got
    derived[SIG_GET_POOL_TVL_PAGED] = selector(SIG_GET_POOL_TVL_PAGED).hex()
    derived[SIG_GET_POOL_TVL_PAGED5] = selector(SIG_GET_POOL_TVL_PAGED5).hex()
    return derived
