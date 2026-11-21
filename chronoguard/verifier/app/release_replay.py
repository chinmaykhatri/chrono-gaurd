"""Controlled policy comparison on frozen release evidence and a fixed traffic trace."""

from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import time


def timestamp(value):
    return int(datetime.fromisoformat(value).timestamp())


def snapshot_at(history, instant):
    return next(item for item in reversed(history) if timestamp(item["effective_at"]) <= instant)


def points(values):
    ordered = sorted(values)
    return {f"p{label}": round(ordered[math.ceil(len(ordered) * label / 100) - 1], 5)
            for label in (50, 95, 99)}


def request_trace(spec):
    requests = []
    for window in spec["traffic"]:
        start = datetime.fromisoformat(window["start"])
        step = spec["traffic_step_minutes"]
        for minute in range(0, window["hours"] * 60, step):
            for index, route in enumerate(window["routes"]):
                at = start + timedelta(minutes=minute + index * 11)
                requests.append({"at": at.isoformat(), "route": route})
    requests.sort(key=lambda row: row["at"])
    return [{**row, "id": f"request-{index:03d}"} for index, row in enumerate(requests, 1)]


def run_replay(trace):
    variants = [("cache_only", None), *(("fixed_ttl", hours) for hours in trace["fixed_ttl_hours"]),
                ("always_verify", None), ("claim_ledger", None)]
    events = request_trace(trace)
    histories = trace["facts"]
    routes = trace["routes"]
    rows, summaries = [], []
    for strategy, ttl in variants:
        name = f"fixed_ttl_{ttl}h" if ttl is not None else strategy
        answers, ledger = {}, {}
        times = defaultdict(list)
        for event in events:
            now = timestamp(event["at"])
            route = event["route"]
            fact_ids = routes[route]["facts"]
            truth = {fact: snapshot_at(histories[fact]["history"], now) for fact in fact_ids}
            started = time.perf_counter_ns()
            prior = answers.get(route)
            cached = prior is not None and (ttl is None or now < prior[0] + ttl * 3600)
            if cached:
                values = dict(prior[1])
            elif now >= timestamp(routes[route]["observed_by_provider_at"]):
                values = {fact: snapshot["value"] for fact, snapshot in truth.items()}
            else:
                values = dict(routes[route]["provider_values"])
            was_stale = any(values[fact] != snapshot["value"] for fact, snapshot in truth.items())
            generated, credits, used = int(not cached), 0, []
            changed = set()
            for fact in fact_ids:
                definition = histories[fact]
                if definition["interval_hours"] is None or strategy == "cache_only":
                    continue
                if strategy == "fixed_ttl" and cached:
                    continue
                previous = ledger.get(fact)
                if strategy != "claim_ledger" or previous is None or now >= previous[0]:
                    snapshot = truth[fact]
                    credits += definition["credits"]
                    ledger[fact] = (now + definition["interval_hours"] * 3600, snapshot)
                    used.append({"fact": fact, "url": snapshot["url"], "sha256": sha256(
                        json.dumps(snapshot, sort_keys=True).encode()).hexdigest()})
                supported = ledger[fact][1]["value"]
                if supported != values[fact]:
                    changed.add(fact)
                values[fact] = supported
            # Other routes retain their raw response until requested. On a hit
            # the shared fact revision independently detects every stale claim.
            issued = now if not cached or changed else prior[0]
            answers[route] = (issued, values)
            generated += int(bool(changed))
            still_stale = any(values[fact] != snapshot["value"] for fact, snapshot in truth.items())
            path = "repair" if changed else "hit" if cached else "miss"
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            times[path].append(elapsed)
            rows.append({
                "variant": name, "request_id": event["id"], "at": event["at"], "route": route, "path": path,
                "cache_hit": cached, "stale_candidate": was_stale, "stale_served": still_stale,
                "false_correction": bool(changed) and not was_stale,
                "repaired": bool(changed) and was_stale and not still_stale,
                "gold": {fact: snapshot["value"] for fact, snapshot in truth.items()}, "returned": values,
                "source_checks": used, "credits": credits, "provider_calls": generated, "replay_cpu_ms": elapsed,
            })
        items = [row for row in rows if row["variant"] == name]
        hits = [row for row in items if row["cache_hit"]]
        stale_hits = sum(row["stale_served"] for row in hits)
        credits = sum(row["credits"] for row in items)
        summaries.append({
            "variant": name, "requests": len(items), "eligible_hits": len(hits), "stale_hits": stale_hits,
            "stale_per_1000_hits": round(1000 * stale_hits / len(hits), 2) if hits else None,
            "credits_per_1000_requests": round(1000 * credits / len(items), 2),
            "credits": credits, "provider_calls": sum(row["provider_calls"] for row in items),
            "repairs": sum(row["repaired"] for row in items),
            "false_corrections": sum(row["false_correction"] for row in items),
            "replay_cpu_ms_by_path": {path: points(values) for path, values in times.items()},
        })
    return {
        "status": "complete", "provenance": "controlled_replay",
        "description": "Policy replay with oracle snapshots, scripted provider values, and configured credit units. Timings cover local policy execution.",
        "dataset_sha256": sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest(),
        "metrics": {"requests_per_variant": len(events), "variants": len(variants)},
        "variants": summaries, "rows": rows,
    }
