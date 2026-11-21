#!/usr/bin/env python3
"""Run the frozen release policy replay and optionally write its raw report."""

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "verifier"))

from app.release_replay import run_replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    trace = json.loads((HERE / "dataset" / "release-replay.json").read_text(encoding="utf-8"))
    report = run_replay(trace)
    print(report["description"])
    print(f"{'Variant':<18} {'Stale hits / 1000':>18} {'Credits / 1000 req':>20} {'Repairs':>8}")
    for row in report["variants"]:
        stale = row["stale_per_1000_hits"]
        print(f"{row['variant']:<18} {str(stale):>18} {row['credits_per_1000_requests']:>20.2f} {row['repairs']:>8}")
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
