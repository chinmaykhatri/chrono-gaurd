"""
ChronoGuard Semantic-Hit Guard Evaluation Runner
Runs the pure-Go guardeval binary or verifies guard performance over eval/guard_pairs.json.
Reports precision, recall, F1, accuracy, and average latency overhead.
"""

import json
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    dataset_path = root / "eval" / "guard_pairs.json"
    report_path = root / "eval" / "reports" / "guard-eval.json"
    guardeval_bin = root / "bifrost" / "plugins" / "chronoguard" / "guardeval.exe"

    if not dataset_path.exists():
        print(f"Error: Dataset {dataset_path} not found.")
        sys.exit(1)

    # If binary doesn't exist, build it
    if not guardeval_bin.exists():
        print("Building guardeval binary...")
        plugin_dir = root / "bifrost" / "plugins" / "chronoguard"
        res = subprocess.run(
            ["go", "build", "-o", "guardeval.exe", "./cmd/guardeval"],
            cwd=str(plugin_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"Error building guardeval: {res.stderr}")
            sys.exit(1)

    print(f"Running guardeval on {dataset_path}...")
    res = subprocess.run(
        [str(guardeval_bin), "-dataset", str(dataset_path), "-output", str(report_path)],
        capture_output=True,
        text=True,
    )
    print(res.stdout)
    if res.returncode != 0:
        print(f"Error executing guardeval: {res.stderr}")
        sys.exit(1)

    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Evaluation succeeded: Precision={data.get('precision')}, Recall={data.get('recall')}, F1={data.get('f1')}")


if __name__ == "__main__":
    main()
