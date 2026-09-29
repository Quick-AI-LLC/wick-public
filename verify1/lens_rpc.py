"""ABI + JSON-RPC helpers for ReservesLens / StateView."""
from __future__ import annotations

import json
import re
import time
import urllib.request

from keccak import (
    SIG_ERR_STRING, SIG_GET_POOL_TVL, SIG_GET_POOL_TVL_PAGED,
    SIG_GET_POOL_TVL_PAGED5, SIG_GET_SLOT0, SIG_POOL_NOT_INITIALIZED,
    keccak256, selector,
)


def _w256(x: int) -> bytes:
    return x.to_bytes(32, "big", signed=True) if x < 0 else x.to_bytes(32, "big")


def _addr_word(addr) -> bytes:
    a = addr.lower().replace("0x", "") if isinstance(addr, str) else f"{addr:x}"
    return bytes(12) + bytes.fromhex(a.rjust(40, "0"))


def encode_poolkey(key: dict) -> bytes:
    return (
        _addr_word(key["currency0"])
        + _addr_word(key["currency1"])
        + _w256(int(key["fee"]))
        + _w256(int(key["tickSpacing"]))
        + _addr_word(key["hooks"])
    )


def encode_bytes_tail(b: bytes) -> bytes:
    return _w256(len(b)) + b + b"\x00" * ((32 - len(b) % 32) % 32)


def calldata_get_pool_tvl(manager: str, key: dict) -> bytes:
    return selector(SIG_GET_POOL_TVL) + _addr_word(manager) + encode_poolkey(key)


def calldata_get_pool_tvl_paged(manager: str, key: dict, cursor: bytes,
                                stats_provider: str | None = None,
                                max_reads: int = 0) -> bytes:
    if stats_provider is None and not max_reads:
        head = selector(SIG_GET_POOL_TVL_PAGED) + _addr_word(manager) + encode_poolkey(key)
        head += _w256(7 * 32)
        return head + encode_bytes_tail(cursor)
    sp = stats_provider or "0x" + "00" * 20
    head = selector(SIG_GET_POOL_TVL_PAGED5) + _addr_word(manager) + encode_poolkey(key)
    head += _addr_word(sp) + _w256(9 * 32) + _w256(max_reads)
    return head + encode_bytes_tail(cursor)


def calldata_stateview(selector_sig: str, pool_id: bytes) -> bytes:
    return selector(selector_sig) + pool_id


def pool_id_of(key: dict) -> bytes:
    return keccak256(encode_poolkey(key))


def _read_words(ret: bytes, start: int, count: int):
    if len(ret) < (start + count) * 32:
        raise ValueError(f"short return data: {len(ret)} bytes")
    return [int.from_bytes(ret[(start + i) * 32:(start + i + 1) * 32], "big")
            for i in range(count)]


def decode_pool_tvl(ret: bytes) -> dict:
    w = _read_words(ret, 0, 14)
    sqrt_raw, tick_raw, liq_raw = w[6], w[7], w[8]
    return {
        "coreAmount0": w[0],
        "coreAmount1": w[1],
        "hookReserves0": w[2],
        "hookReserves1": w[3],
        "hookEffective0": w[4],
        "hookEffective1": w[5],
        "sqrtPriceX96": sqrt_raw if sqrt_raw < (1 << 160) else sqrt_raw - (1 << 160),
        "tick": tick_raw - (1 << 256) if tick_raw >= (1 << 255) else tick_raw,
        "activeLiquidity": liq_raw,
        "blockNumber": w[9],
        "statsProvider": "0x" + w[10].to_bytes(32, "big")[12:].hex(),
        "hookPermissions": w[11] & 0xFFFF,
        "hasCustomAccounting": bool(w[12]),
        "statsStatus": w[13] & 0xFF,
    }


def decode_paged_return(ret: bytes) -> tuple:
    w = _read_words(ret, 0, 16)
    tvl = decode_pool_tvl(ret[:14 * 32])
    off, done = w[14], bool(w[15])
    if off == 0:
        return tvl, b"", done
    if off != 16 * 32:
        raise ValueError(f"unexpected nextCursor offset {off}")
    if len(ret) < off + 32:
        raise ValueError("malformed nextCursor tail")
    ln = int.from_bytes(ret[off:off + 32], "big")
    if off + 32 + ln > len(ret):
        raise ValueError("malformed nextCursor tail")
    return tvl, ret[off + 32: off + 32 + ln], done


def decode_slot0(ret: bytes) -> dict:
    w = _read_words(ret, 0, 4)
    tick = w[1] - (1 << 256) if w[1] >= (1 << 255) else w[1]
    return {"sqrtPriceX96": w[0], "tick": tick, "protocolFee": w[2] & 0xFFFFFF,
            "lpFee": w[3] & 0xFFFFFF}


def decode_revert_reason(data: bytes) -> str | None:
    if len(data) >= 100 and data[:4] == selector(SIG_ERR_STRING):
        ln = int.from_bytes(data[36:68], "big")
        try:
            return data[68:68 + ln].decode("utf-8", "replace")
        except Exception:
            return None
    if data[:4] == selector(SIG_POOL_NOT_INITIALIZED):
        return "PoolNotInitialized"
    return None


_OOG_RE = re.compile(r"out of gas|gas required|exceeds.*gas|too large|gas limit", re.I)


class RpcError(Exception):
    def __init__(self, message: str, kind: str, data: bytes = b""):
        super().__init__(message)
        self.kind = kind
        self.data = data


class JsonRpc:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self._id = 0

    def _post(self, method, params):
        self._id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self._id,
                              "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=payload,
                                     headers={
                                         "Content-Type": "application/json",
                                         "User-Agent": "WickCapture/1.0 (+https://wick.green)",
                                     })
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = json.loads(r.read())
                if "error" in body:
                    msg = body["error"].get("message", "")
                    data_hex = body["error"].get("data", "")
                    data = bytes.fromhex(data_hex[2:]) if isinstance(data_hex, str) \
                        and data_hex.startswith("0x") and len(data_hex) > 2 else b""
                    if _OOG_RE.search(msg):
                        raise RpcError(msg, "oog", data)
                    if data[:4] == selector(SIG_ERR_STRING) or data:
                        reason = decode_revert_reason(data)
                        raise RpcError(reason or msg, "revert", data)
                    raise RpcError(msg, "rpc", data)
                return body["result"]
            except RpcError:
                raise
            except urllib.error.HTTPError as e:
                body_text = e.read().decode("utf-8", "replace") if e.fp else ""
                if _OOG_RE.search(body_text):
                    raise RpcError(body_text[:300], "oog")
                last = RpcError(f"HTTP {e.code}: {body_text[:200]}", "transport")
            except Exception as e:
                last = RpcError(f"{type(e).__name__}: {e}", "transport")
            time.sleep(0.4 * (attempt + 1))
        raise last

    def block_number(self) -> int:
        return int(self._post("eth_blockNumber", []), 16)

    def chain_id(self) -> int:
        return int(self._post("eth_chainId", []), 16)

    def call(self, to: str, data: bytes, block: int | str, gas: int) -> bytes:
        tx = {"to": to, "data": "0x" + data.hex()}
        if gas:
            tx["gas"] = hex(gas)
        blk = hex(block) if isinstance(block, int) else block
        ret = self._post("eth_call", [tx, blk])
        return bytes.fromhex(ret[2:]) if ret and ret != "0x" else b""
