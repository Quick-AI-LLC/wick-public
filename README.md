# wick-public

First-party **Arc mainnet** capture for Wick.

Live product: [wick.green](https://wick.green) (chain 5042). The charting interface is **not** in this repository.

This repo is the read path a reviewer can clone:

1. Talk to Arc (`https://rpc.mainnet.arc.io`).
2. Snapshot USDC-pool state (v3 pair reserves, v4 StateView + ReservesLens).
3. Turn those snapshots into OHLC candles and **Delta** (net ΔUSDC).

No signing. No private RPC. No warehouse dump.

## What Wick uses Arc for

Every pool Wick charts is token/USDC on Arc. Native gas is USDC (18-dec); `0x3600…0000` is the 6-dec ERC-20 view of the same balance.

- **v3** — `token0()` / `token1()` at read time. Quote is `address(0)` (native-18) or the USDC predeploy (ERC-20-6). Reserves are `eth_getBalance` / `balanceOf`.
- **v4** — price from `StateView.getSlot0` (`0xF3334192D15450CdD385c8B70e03f9A6bD9E673b`). Reserves from `ReservesLens.getPoolTVL` (`0x0000001b173C3bbF3984D417d8614E3eed34865B`). Amounts are never derived from `getLiquidity`.

A failed reserve read is a **status**, never a silent zero.

## Reproduce (one command)

```bash
python3 -m pip install -r requirements.txt
python3 snapshotter.py
```

Writes one JSONL row per pool under `./out/` against public Arc RPC. Takes about a minute.

Offline metric check (no RPC):

```bash
python3 metric/test_metric.py
python3 scripts/show_delta.py fixtures/ARGUS__v3__1%.sample.jsonl
```

## OHLC-M

Wick does not index swap logs and does not claim traded volume.

| Letter | Source |
|---|---|
| O H L C | 15-minute `price_usdc_per_token` samples, bucketed. A 1H candle is four samples. |
| M (Delta) | `display_USDC(t) − display_USDC(t−1)` on the same pool. Net change, not gross flux. |

Admission into Delta: unhooked pool, ERC-20 USDC representation, `reserve_read_status` not dead, reserve present. Hooked v4 pools stay **price-only**.

See `schema.md`, `metric/ohlc.py`, `metric/delta.py`.

## Layout

```
snapshotter.py                 # v3 + v4 capture
verify1/v4_reserve_reader.py   # ReservesLens
verify1/lens_rpc.py            # ABI + public RPC
verify1/keccak.py              # selectors
verify1/peg_check.py           # PoolKey + 18↔6 orientation
config/founding-pools.public.json
metric/{ohlc,delta}.py
fixtures/ARGUS__v3__1%.sample.jsonl
```

Demo pools in this repo: cirBTC, ARGUS, NVDA, EURC, WETH. Addresses are on-chain. This is a subset, not the full Wick catalog.

## Status

Public capture kit for wick.green on Arc mainnet (chain 5042).
