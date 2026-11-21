"""Run the current pure-Go guard against labeled fixture pairs."""

import argparse
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=root / "eval/guard_pairs.json")
    parser.add_argument("--output", type=Path, default=root / "eval/reports/local/guard-eval.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["go", "run", "./cmd/guardeval", "-dataset", str(args.dataset.resolve()), "-output", str(args.output.resolve())],
        cwd=root / "bifrost/plugins/chronoguard",
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
