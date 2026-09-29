"""Delta = net change in display-USDC between two snapshots of the same pool.

This is Wick's house metric. It is not traded volume and not order-flow.
A swap against a USDC pool *is* an inventory change; Delta records that
change in the quote unit.

Rules:
  - convert raw reserves with the row's own usdc_dec (6 or 18). Never mix raws.
  - reserve_read_status in DEAD_STATUS, or a missing reserve, is null — not 0.
  - usdc_representation == "native" is excluded from mixed $ aggregates
    (18-dec native USDC is the same asset, different view; mixing scales 1e12).
  - hooked pools (hooks != 0x0) are price-only; they do not enter Delta.
"""
from __future__ import annotations
from decimal import Decimal, getcontext

getcontext().prec = 40

DEAD_STATUS = frozenset({
    "custom_accounting", "unreadable", "reader_error", "not_initialized",
})
ZERO_HOOKS = frozenset({
    "0x0000000000000000000000000000000000000000", "0x0", "0", "", None,
})


def display_usdc(raw, dec) -> Decimal | None:
    if raw is None or dec is None:
        return None
    return Decimal(str(raw)) / (Decimal(10) ** int(dec))


def _hooks_ok(row) -> bool:
    hooks = row.get("hooks")
    if hooks is None:
        return True
    return str(hooks).lower() in ZERO_HOOKS


def row_admitted(row) -> bool:
    if not _hooks_ok(row):
        return False
    if row.get("usdc_representation") == "native":
        return False
    status = row.get("reserve_read_status")
    if status and status in DEAD_STATUS:
        return False
    if row.get("usdc_reserve_raw") is None:
        return False
    return True


def delta_between(prev, curr) -> Decimal | None:
    """Net display-USDC change from prev row to curr row. None if either is inadmissible."""
    if not row_admitted(prev) or not row_admitted(curr):
        return None
    a = display_usdc(prev["usdc_reserve_raw"], prev.get("usdc_dec"))
    b = display_usdc(curr["usdc_reserve_raw"], curr.get("usdc_dec"))
    if a is None or b is None:
        return None
    return b - a
