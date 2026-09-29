#!/usr/bin/env python3
"""Print per-row Delta from a JSONL capture file. No RPC."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metric.delta import delta_between, display_usdc, row_admitted

def main(path):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    prev = None
    print(f"{'ts':<28} {'status':<18} {'display_usdc':>16} {'delta':>16}")
    for r in rows:
        admitted = row_admitted(r)
        disp = display_usdc(r.get("usdc_reserve_raw"), r.get("usdc_dec")) if admitted else None
        d = delta_between(prev, r) if prev is not None else None
        print(f"{str(r.get('ts','')):<28} {str(r.get('reserve_read_status') or ''):<18} "
              f"{str(disp if disp is not None else '—'):>16} {str(d if d is not None else '—'):>16}")
        if admitted:
            prev = r

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 scripts/show_delta.py fixtures/ARGUS__v3__1%.sample.jsonl")
    main(sys.argv[1])
