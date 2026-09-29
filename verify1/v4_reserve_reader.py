"""
v4 reserve reader for Arc mainnet (chain 5042).

ReservesLens.getPoolTVL / getPoolTVLPaged at 0x0000001b173C3bbF3984D417d8614E3eed34865B.
A failed or custom-accounting read is a status, never a silent zero reserve.
"""
from __future__ import annotations

from keccak import assert_selectors
from lens_rpc import (
    JsonRpc, RpcError, calldata_get_pool_tvl, calldata_get_pool_tvl_paged,
    calldata_stateview, decode_paged_return, decode_pool_tvl, decode_revert_reason,
    decode_slot0, pool_id_of, SIG_GET_SLOT0,
)

GREEN = "green"
UNREADABLE = "unreadable"
CUSTOM_ACCOUNTING = "custom_accounting"
NOT_INITIALIZED = "not_initialized"

DEFAULT_GAS = 50_000_000
MAX_PAGES = 128


class ReserveResult:
    def __init__(self, status: str, tvl: dict | None, pages: int, block: int, note: str = ""):
        self.status, self.tvl, self.pages, self.block, self.note = status, tvl, pages, block, note

    def to_row_fragment(self, cfg: dict) -> dict:
        frag = {
            "sqrtPriceX96": None, "tick": None, "onchain_fee": cfg.get("fee"),
            "liquidity": None,
            "usdc_reserve_raw": None, "token_reserve_raw": None,
            "reserve_read_status": self.status,
        }
        if self.status == GREEN:
            usdc_side = int(cfg["usdc_side"])
            frag["usdc_reserve_raw"] = self.tvl[f"coreAmount{usdc_side}"]
            frag["token_reserve_raw"] = self.tvl[f"coreAmount{1 - usdc_side}"]
            frag["sqrtPriceX96"] = self.tvl["sqrtPriceX96"]
            frag["tick"] = self.tvl["tick"]
            frag["liquidity"] = self.tvl["activeLiquidity"]
        elif self.tvl is not None:
            frag["sqrtPriceX96"] = self.tvl["sqrtPriceX96"]
            frag["tick"] = self.tvl["tick"]
            frag["liquidity"] = self.tvl["activeLiquidity"]
        if self.note:
            frag["reserve_note"] = self.note
        return frag


class V4ReserveReader:
    def __init__(self, rpc_url: str, pool_manager: str, lens: str,
                 gas: int = DEFAULT_GAS, max_reads: int = 0):
        assert_selectors()
        self.rpc = JsonRpc(rpc_url)
        self.manager = pool_manager
        self.lens = lens
        self.gas = gas
        self.max_reads = max_reads

    def slot0(self, key: dict, block: int) -> dict:
        data = calldata_stateview(SIG_GET_SLOT0, pool_id_of(key))
        ret = self.rpc.call("0xF3334192D15450CdD385c8B70e03f9A6bD9E673b", data, block, self.gas)
        return decode_slot0(ret)

    def _non_paged(self, key: dict, block: int) -> dict:
        ret = self.rpc.call(self.lens, calldata_get_pool_tvl(self.manager, key), block, self.gas)
        if not ret:
            raise RpcError("empty return (non-paged)", "oog")
        return decode_pool_tvl(ret)

    def _paged(self, key: dict, block: int) -> tuple:
        cursor, pages = b"", 0
        while True:
            ret = self.rpc.call(
                self.lens,
                calldata_get_pool_tvl_paged(self.manager, key, cursor, None, self.max_reads),
                block, self.gas,
            )
            if not ret:
                raise RpcError("empty return (paged)", "oog")
            tvl, nxt, done = decode_paged_return(ret)
            pages += 1
            if done:
                return tvl, pages
            if not nxt:
                raise RpcError("protocol violation: done=false with empty nextCursor", "rpc")
            if pages >= MAX_PAGES:
                raise RpcError(f"exceeded MAX_PAGES={MAX_PAGES}", "rpc")
            cursor = nxt

    def read(self, key: dict) -> ReserveResult:
        block = self.rpc.block_number()
        tvl = None
        pages = 0
        note = ""
        try:
            tvl = self._non_paged(key, block)
        except RpcError as e:
            first = f"non-paged {e.kind}: {e}"
            try:
                tvl, pages = self._paged(key, block)
                note = first + " -> paged OK"
            except RpcError as e2:
                if e.kind == "revert" and decode_revert_reason(e.data) == "PoolNotInitialized":
                    return ReserveResult(NOT_INITIALIZED, None, 0, block, "PoolNotInitialized")
                return ReserveResult(
                    UNREADABLE, None, pages, block, f"{first} | paged {e2.kind}: {e2}"
                )
        if tvl["hasCustomAccounting"]:
            return ReserveResult(CUSTOM_ACCOUNTING, tvl, pages, block,
                                 note or "hasCustomAccounting=true -> price-only")
        return ReserveResult(GREEN, tvl, pages, block, note)
