#!/usr/bin/env python3
"""ChronoGuard verify-proof: Gate G1 verification suite.

Runs a comprehensive check of all provable claims and prints a PASS/FAIL table.
Every number is labeled LIVE, SIMULATED, or TARGET.
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERIFIER_URL = os.environ.get("CG_VERIFIER_URL", "http://127.0.0.1:8000")
BIFROST_URL = os.environ.get("CG_BIFROST_URL", "http://127.0.0.1:8089")

RESULTS = []

def check(name: str, passed: bool, detail: str, label: str = "LIVE"):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "label": label})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name} [{label}] — {detail}")


def run_go_tests():
    print("\n--- Go Plugin Tests ---")
    try:
        result = subprocess.run(
            ["go", "test", "./..."],
            cwd=str(BASE_DIR / "bifrost" / "plugins" / "chronoguard"),
            capture_output=True, text=True, timeout=120
        )
        passed = result.returncode == 0
        packages = [line for line in result.stdout.strip().split("\n") if line.startswith("ok")]
        check("go_test_all", passed, f"{len(packages)} packages passed" if passed else result.stderr[:200])
    except Exception as e:
        check("go_test_all", False, str(e))


def run_pytest():
    print("\n--- Python Verifier Tests ---")
    try:
        result = subprocess.run(
            ["uv", "run", "pytest", "-q", "--tb=short"],
            cwd=str(BASE_DIR / "verifier"),
            capture_output=True, text=True, timeout=120
        )
        passed = result.returncode == 0
        lines = result.stdout.strip().split("\n")
        summary = lines[-1] if lines else "no output"
        check("pytest_all", passed, summary if passed else result.stdout[:300])
    except Exception as e:
        check("pytest_all", False, str(e))


def run_console_build():
    print("\n--- Console Build ---")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(BASE_DIR / "console"),
            capture_output=True, text=True, timeout=120,
            shell=True,
        )
        passed = result.returncode == 0
        check("console_build", passed, "TypeScript + Vite build succeeded" if passed else result.stderr[:300])
    except Exception as e:
        check("console_build", False, str(e))


def check_services():
    print("\n--- Service Health ---")
    import httpx
    # Verifier
    try:
        r = httpx.get(f"{VERIFIER_URL}/healthz", timeout=3)
        check("verifier_health", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        check("verifier_health", False, str(e))

    # Bifrost
    try:
        r = httpx.get(f"{BIFROST_URL}/health", timeout=3)
        check("bifrost_health", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        check("bifrost_health", False, str(e), label="SIMULATED")

    # Verifier readyz
    try:
        r = httpx.get(f"{VERIFIER_URL}/readyz", timeout=3)
        data = r.json()
        check("postgres_ready", data.get("postgres", False), "Connected" if data.get("postgres") else "Unavailable")
        check("redis_ready", data.get("redis", False), "Connected" if data.get("redis") else "Unavailable")
        check("tavily_key", data.get("tavily_key_present", False), "Present" if data.get("tavily_key_present") else "Missing")
    except Exception as e:
        check("readyz", False, str(e))


def check_e2e_reports():
    print("\n--- E2E Live Reports ---")
    reports_dir = BASE_DIR / "eval" / "reports"
    e2e_logs = sorted(reports_dir.glob("e2e-live-*.log")) if reports_dir.exists() else []
    if e2e_logs:
        latest = e2e_logs[-1]
        content = latest.read_text(encoding="utf-8")
        all_passed = "ALL 6 SCENARIOS PASSED" in content
        check("e2e_live_latest", all_passed, f"{latest.name}: {'ALL PASS' if all_passed else 'FAILURES DETECTED'}")
    else:
        check("e2e_live_latest", False, "No e2e-live report found. Run scripts/e2e_live.ps1")


def check_no_fabricated_data():
    print("\n--- Data Integrity ---")
    # Check for hard-coded placeholder values in the console
    console_src = BASE_DIR / "console" / "src"
    suspicious = []
    if console_src.exists():
        for f in console_src.rglob("*.tsx"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            for pattern in ["Math.random()", "faker.", "lorem ipsum"]:
                if pattern.lower() in content.lower():
                    suspicious.append(f"{f.name}: {pattern}")
        for f in console_src.rglob("*.ts"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            for pattern in ["Math.random()", "faker.", "lorem ipsum"]:
                if pattern.lower() in content.lower():
                    suspicious.append(f"{f.name}: {pattern}")
    check("no_fabricated_ui", len(suspicious) == 0, f"Clean" if not suspicious else f"Found: {'; '.join(suspicious[:5])}")


def print_summary():
    print("\n" + "=" * 72)
    print("  CHRONOGUARD VERIFY-PROOF GATE G1 RESULTS")
    print("=" * 72)
    print(f"  {'Test':<35} {'Status':<8} {'Label':<12} Detail")
    print("  " + "-" * 68)
    passed_count = 0
    failed_count = 0
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        icon = "✓" if r["passed"] else "✗"
        print(f"  {icon} {r['name']:<33} {status:<8} {r['label']:<12} {r['detail'][:40]}")
        if r["passed"]:
            passed_count += 1
        else:
            failed_count += 1

    print("  " + "-" * 68)
    all_pass = failed_count == 0
    gate = "GATE G1: PASS" if all_pass else "GATE G1: FAIL"
    print(f"  {gate}  ({passed_count} passed, {failed_count} failed)")
    print(f"  Timestamp: {datetime.now(UTC).isoformat()}")
    print("=" * 72)

    # Save report
    report_dir = BASE_DIR / "eval" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"verify-proof-{ts}.json"
    report_path.write_text(json.dumps({
        "gate": "G1",
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": all_pass,
        "results": RESULTS,
    }, indent=2))
    print(f"  Report: {report_path}")

    return 0 if all_pass else 1


def main():
    print("=" * 72)
    print("  ChronoGuard verify-proof (Gate G1)")
    print(f"  {datetime.now(UTC).isoformat()}")
    print("=" * 72)

    run_go_tests()
    run_pytest()
    run_console_build()

    # Service checks are optional (may not be running during CI)
    try:
        import httpx
        check_services()
    except ImportError:
        print("\n--- Service Health (SKIPPED: httpx not available) ---")

    check_e2e_reports()
    check_no_fabricated_data()

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
