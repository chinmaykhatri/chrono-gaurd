"""Measure loopback HTTP latency for a fresh hit and the same request with caching disabled."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from time import perf_counter_ns, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def percentiles(samples):
    ordered = sorted(samples)
    return {
        f"p{n}": round(ordered[math.ceil(n * len(ordered) / 100) - 1], 3)
        for n in (50, 95, 99)
    }


def run(gateway, fixture, trials, samples):
    for url in (gateway, fixture):
        if urlsplit(url).hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Use an isolated local replay deployment.")
    question = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "What is the latest major Go release?"}
        ],
    }
    rows = []
    with httpx.Client(timeout=30, trust_env=False) as client:

        def counters():
            return client.get(fixture + "/metrics").raise_for_status().json()["counts"]

        def call(headers):
            start = perf_counter_ns()
            response = client.post(
                gateway + "/v1/chat/completions", json=question, headers=headers
            )
            elapsed = (perf_counter_ns() - start) / 1e6
            response.raise_for_status()
            assert "Go 1.24" in response.json()["choices"][0]["message"]["content"]
            return elapsed, response.headers.get("x-bifrost-cache-hit") == "true"

        for trial in range(trials):
            headers = {"x-cg-policy": "strict", "x-bf-cache-key": "perf-" + uuid4().hex}
            disabled = {
                **headers,
                "x-bf-cache-type": "off",
                "x-bf-cache-no-store": "true",
            }
            call(headers)
            for _ in range(20):
                sleep(0.1)
                if call(headers)[1]:
                    break
            else:
                raise RuntimeError("Warm-up never produced an actual cache hit")
            call(disabled)
            for pair in range(samples):
                order = (
                    ["fresh_hit", "cache_disabled"]
                    if (trial + pair) % 2 == 0
                    else ["cache_disabled", "fresh_hit"]
                )
                for path in order:
                    previous = counters()
                    ms, hit = call(headers if path == "fresh_hit" else disabled)
                    calls = {k: v - previous.get(k, 0) for k, v in counters().items()}
                    if hit != (path == "fresh_hit") or calls.get(
                        "generation", 0
                    ) != int(path == "cache_disabled"):
                        raise RuntimeError(
                            "Cache or provider telemetry disagrees with assigned path"
                        )
                    rows.append(
                        {
                            "trial": trial + 1,
                            "pair": pair + 1,
                            "path": path,
                            "elapsed_ms": round(ms, 3),
                            "calls": calls,
                        }
                    )
    metrics = {}
    for mode in ("fresh_hit", "cache_disabled"):
        sample = [r for r in rows if r["path"] == mode]
        calls = Counter()
        for row in sample:
            calls.update(row["calls"])
        metrics[mode] = {
            "n": len(sample),
            "latency_ms": percentiles([r["elapsed_ms"] for r in sample]),
            "fixture_calls": dict(calls),
        }
    return {
        "scope": "Bifrost public loopback HTTP, local fixture generation and embedding; no external billing",
        "method": "Sequential paired requests with alternating order; separate call-counter requests excluded from latency. Fresh namespaces and warm-ups per trial.",
        "trials": trials,
        "pairs_per_trial": samples,
        "metrics": metrics,
        "rows": rows,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gateway", default="http://localhost:8080")
    p.add_argument("--fixture", default="http://127.0.0.1:8099")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--samples", type=int, default=20)
    a = p.parse_args()
    if min(a.trials, a.samples) < 1:
        p.error("Specify positive trial and sample counts")
    report = run(a.gateway, a.fixture, a.trials, a.samples)
    a.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"]))
