"""Replay checks against first uploads of stable PyPI distributions, using earlier releases for fitting."""

import argparse
import bisect
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verifier"))
from app.pipeline.scheduler import estimate_lambda, solve_lagrangian_budget

PACKAGES = ("certifi", "click", "packaging", "requests", "sqlalchemy", "urllib3")
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
SPLIT = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=6)
SNAPSHOT = ROOT / "eval/dataset/pypi-release-history.json"


def fetch_snapshot():
    facts = {}
    for name in PACKAGES:
        url = f"https://pypi.org/pypi/{name}/json"
        with urllib.request.urlopen(url, timeout=60) as response:
            releases = json.load(response)["releases"]
        events = []
        for version, items in releases.items():
            if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version) or not items:
                continue
            first = min(i["upload_time_iso_8601"] for i in items)
            when = datetime.fromisoformat(first.replace("Z", "+00:00"))
            if when < END:
                events.append([when.isoformat(), version])
        events.sort()
        earlier = [r for r in events if datetime.fromisoformat(r[0]) < START]
        facts[name] = {
            "source": url,
            "events": earlier[-1:]
            + [r for r in events if datetime.fromisoformat(r[0]) >= START],
        }
    SNAPSHOT.write_text(
        json.dumps(
            {
                "definition": "Version whose stable numeric distribution was first uploaded most recently; includes maintenance lines. Deleted releases may be absent from the registry.",
                "facts": facts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def benchmark(snapshot, traces):
    data = json.loads(snapshot.read_bytes())["facts"]
    events = {
        name: [(datetime.fromisoformat(ts), version) for ts, version in row["events"]]
        for name, row in data.items()
    }

    def answer(name, when):
        idx = bisect.bisect_right([e[0] for e in events[name]], when) - 1
        if idx < 0:
            raise ValueError("Missing version preceding window")
        return events[name][idx][1]

    fit = []
    for name in PACKAGES:
        prev = answer(name, START)
        day = START + timedelta(days=1)
        changed = 0
        checks = 0
        while day < SPLIT:
            v = answer(name, day)
            changed += int(v != prev)
            checks += 1
            prev = v
            day += timedelta(days=1)
        fit.append(
            {
                "name": name,
                "class_key": "software_versions",
                "query_hits": checks,
                "credits_per_check": 1,
                "lambda_hat": estimate_lambda(
                    checks, changed, 86400, "software_versions"
                ),
            }
        )
    budget = len(PACKAGES) / 24
    intervals = {
        r["name"]: r["optimal_interval_s"] for r in solve_lagrangian_budget(fit, budget)
    }
    tight_budget = len(PACKAGES) / (7 * 24)
    constrained = {
        r["name"]: r["optimal_interval_s"]
        for r in solve_lagrangian_budget(fit, tight_budget)
    }
    totals = {}
    with gzip.open(traces, "wt", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ("policy", "timestamp", "package", "expected", "served", "checked")
        )
        for policy, seconds in (
            ("cache_only", float("inf")),
            ("fixed_24h", 86400),
            ("fixed_48h", 172800),
            ("fixed_7d", 604800),
            ("always_verify", 0),
            ("scheduler", None),
            ("scheduler_weekly_budget", None),
        ):
            last = {}
            stored = {}
            cost = stale = n = 0
            at = SPLIT
            while at < END:
                for name in PACKAGES:
                    gold = answer(name, at)
                    learned = (
                        constrained
                        if policy == "scheduler_weekly_budget"
                        else intervals
                    )
                    due = name not in last or (at - last[name]).total_seconds() >= (
                        learned[name] if seconds is None else seconds
                    )
                    if due:
                        stored[name] = gold
                        last[name] = at
                        cost += 1
                    stale += int(stored[name] != gold)
                    n += 1
                    writer.writerow(
                        (policy, at.isoformat(), name, gold, stored[name], int(due))
                    )
                at += STEP
            totals[policy] = {
                "requests": n,
                "stale_served": stale,
                "registry_checks": cost,
            }
    return {
        "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "scope": "Publisher timestamps supply independent labels. Request traffic, checks and perfect retrieval are simulated. No LLM or Tavily billing.",
        "train": "2024, daily sampled changes",
        "test": "2025, one query per package every six hours",
        "target_checks_per_hour": budget,
        "learned_interval_seconds": intervals,
        "weekly_budget_checks_per_hour": tight_budget,
        "weekly_budget_intervals": constrained,
        "policies": totals,
        "traces": traces.name,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly refresh the public publisher snapshot.",
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.refresh:
        fetch_snapshot()
    report = benchmark(SNAPSHOT, args.output.with_suffix(".csv.gz"))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["policies"]))
