#!/usr/bin/env python3
"""Run current ChronoGuard component tests and the public gateway replay."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        parser.error("npm is required")
    checks = [
        ("pinned_gateway_source", [sys.executable, "bifrost/prepare.py"], ROOT),
        ("go_tests", ["go", "test", "./..."], ROOT / "bifrost/plugins/chronoguard"),
        ("verifier_tests", [sys.executable, "-m", "pytest", "-q"], ROOT / "verifier"),
        ("console_build", [npm, "run", "build"], ROOT / "console"),
        ("console_tests", [npm, "test"], ROOT / "console"),
        ("policy_replay", [sys.executable, "eval/run_eval.py"], ROOT),
    ]
    if not args.component_only:
        checks.append(("bifrost_http_fixture_replay", [sys.executable, "scripts/release_demo.py"], ROOT))

    results = []
    for name, command, cwd in checks:
        print(f"Running {name}", flush=True)
        status = subprocess.run(command, cwd=cwd).returncode
        results.append({"check": name, "passed": status == 0, "exit_code": status})

    report = {
        "scope": "component_checks" if args.component_only else "components_and_public_gateway",
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": all(item["passed"] for item in results), "results": results,
    }
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
