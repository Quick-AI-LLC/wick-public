# Snapshot row

One JSON object per line, one file per pool: `<SYMBOL>__<version>__<fee>.jsonl`.

## Common

| Field | Meaning |
|---|---|
| `ts` | UTC ISO-8601 of the snapshot |
| `block` | `eth_blockNumber` at capture |
| `symbol` / `pool` / `version` / `fee` | identity |
| `token_ca` | token address |
| `price_usdc_per_token` | display USDC per token, or `null` |
| `token_decimals` | on-chain `decimals()` |
| `usdc_dec` | 6 (ERC-20 predeploy) or 18 (native) |
| `usdc_representation` | `erc20` or `native` |
| `usdc_reserve_raw` | integer string, or `null` |
| `token_reserve_raw` | integer string, or `null` |
| `reserve_read_status` | `green` \| `custom_accounting` \| `unreadable` \| `reader_error` \| `not_initialized` |

Raw reserves are the record. Price is derived and can be recomputed.

## v3 extras

`lp`, `quote_addr`, `token_is_c0`. Orientation is read from `token0()`/`token1()` at capture, not trusted from config.

## v4 extras

`pool_id`, `sqrtPriceX96`, `tick`, `onchain_fee`, `hooks`, `usdc_side`. Reserves come from ReservesLens `coreAmount0/1`. Hooked pools (`hooks != 0x0`) are admitted for price and excluded from Delta.

## Status contract

`reserve_read_status` other than `green` ⇒ reserves are `null`. Never write `0` for an unreadable pool.
