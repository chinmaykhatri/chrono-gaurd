"""Assert the full Bifrost lifecycle against the isolated release replay stack."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


def run(gateway, fixture, password, console=None):
    console = console or gateway
    for url in (gateway, fixture, console):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Release replay only supports loopback services.")
    trace = []
    namespace = "release-replay-" + uuid4().hex
    with httpx.Client(base_url=console, timeout=22, trust_env=False) as client, httpx.Client(base_url=fixture, timeout=5, trust_env=False) as replay:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if client.get("/readyz", timeout=3).is_success and client.get(gateway + "/v1/models", timeout=3).is_success:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("The verifier or Bifrost did not become ready.")
        login = client.post("/api/v1/auth/login", json={"password": password}, headers={"Origin": console})
        login.raise_for_status()
        csrf = login.json()["csrf_token"]
        browser = {"Origin": console, "X-CSRF-Token": csrf}

        def control(revision, failed=False, lagging=False, scope=namespace):
            replay.post("/control", json={
                "revision": revision, "fail_provider": failed, "provider_lagging": lagging, "scenario_scope": scope,
            }).raise_for_status()

        def clock(action, **params):
            response = client.post("/api/v1/clock", json={"action": action, **params}, headers=browser)
            response.raise_for_status()

        def counters():
            response = replay.get("/metrics")
            response.raise_for_status()
            return response.json()["counts"]

        def chat(case, prompt, suffix, options=None, **payload):
            previous = counters()
            started = time.perf_counter()
            response = client.post(gateway + "/v1/chat/completions", json={
                "model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                **payload,
            }, headers={"x-cg-policy": "strict", "x-bf-cache-key": namespace + suffix, **(options or {})})
            elapsed = (time.perf_counter() - started) * 1000
            current = counters()
            body = response.json()
            row = {
                "case": case, "status": response.status_code, "latency_ms": round(elapsed, 2),
                "cache_id": response.headers.get("x-cg-cache-id") or response.headers.get("x-bifrost-cache-id"),
                "cache_hit": response.headers.get("x-bifrost-cache-hit") == "true",
                "cache_type": response.headers.get("x-bifrost-cache-hit-type"),
                "decision": response.headers.get("x-cg-decision"),
                "shadow_decision": response.headers.get("x-cg-decision-shadow"),
                "response_id": response.headers.get("x-cg-response-id"),
                "error": body.get("error") if not response.is_success else None,
                "calls": {kind: value - previous.get(kind, 0) for kind, value in current.items()},
                "text": body.get("choices", [{}])[0].get("message", {}).get("content"),
            }
            trace.append(row)
            print(json.dumps(row), flush=True)
            return row

        def annotation(row):
            response = client.get(f"/api/v1/responses/{row['response_id']}/annotations")
            response.raise_for_status()
            return response.json()

        try:
            control(0)
            clock("reset")
            first = chat("warm_release_answer", "What is the latest major Go release?", "-release")
            assert first["status"] == 200 and "Go 1.24" in first["text"] and first["cache_id"], first
            assert first["calls"].get("search", 0) == 1, first
            second = chat("warm_release_with_static_control", "What is the latest major Go release, and what is 2 + 2?", "-mixed")
            assert second["status"] == 200 and "2 + 2 = 4" in second["text"], second
            assert first["cache_id"] != second["cache_id"], trace
            assert second["calls"].get("search", 0) == 0, second
            time.sleep(1)  # The pinned Bifrost cache publishes misses asynchronously.
            hit = chat("fresh_paraphrase", "Which Go major version was released most recently?", "-release")
            assert hit["status"] == 200 and hit["cache_type"] == "semantic" and hit["decision"] == "serve", hit
            assert all(hit["calls"].get(kind, 0) == 0 for kind in ("search", "generation", "extraction", "judge")), hit

            manifest = annotation(first)
            claims = manifest.get("claims", [])
            check_at = next(claim["next_check_at"] for claim in claims if claim["class"] == "software_versions")
            offset = max(1, int((datetime.fromisoformat(check_at) - datetime.now(UTC)).total_seconds()) + 2)
            control(1)
            clock("advance", seconds=offset)
            shadow = chat("shadow_observes_due_hit", "What is the latest major Go release?", "-release", {"x-cg-shadow": "1"})
            assert shadow["status"] == 200 and shadow["shadow_decision"] == "revalidate_blocking", shadow
            assert shadow["text"] == first["text"] and shadow["calls"].get("search", 0) == 0, shadow
            repaired = chat("revalidate_and_repair", "What is the latest major Go release?", "-release")
            assert repaired["status"] == 200 and repaired["decision"] == "regenerated" and "Go 1.25" in repaired["text"], repaired
            assert repaired["calls"].get("search", 0) == 1, repaired
            cache_meta = client.get("/api/v1/cache-entries", params={"limit": 100})
            cache_meta.raise_for_status()
            linked = next(row for row in cache_meta.json()["items"] if row.get("bifrost_cache_id") == second["cache_id"])
            assert linked["status"] == "stale", linked

            control(1, failed=True)
            blocked = chat("strict_refuses_during_outage", "What is the latest major Go release, and what is 2 + 2?", "-mixed")
            assert blocked["status"] == 503 and not blocked["text"], blocked
            assert blocked["calls"].get("search", 0) == 0, blocked
            control(1)
            following = chat("next_request_after_exact_eviction", "What is the latest major Go release?", "-release")
            assert following["status"] == 200 and "Go 1.25" in following["text"] and not following["cache_hit"], following
            control(1, lagging=True)
            initial = chat("repair_stale_provider_miss", "What is the latest major Go release?", "-lagging-provider")
            assert initial["status"] == 200 and initial["decision"] == "regenerated" and "Go 1.25" in initial["text"], initial
            assert initial["calls"].get("generation", 0) == 2 and initial["calls"].get("search", 0) == 0, initial
            control(1)
            austria = chat("warm_guard_candidate", "what is the capital of austria?", "-guard")
            assert austria["status"] == 200 and "Vienna" in austria["text"], austria
            time.sleep(1)
            australia = chat("guard_reissues_original_query", "what is the capital of australia?", "-guard", {"x-cg-guard": "1"})
            assert australia["status"] == 200 and australia["decision"] == "guard_bypass" and "Canberra" in australia["text"], australia
            assert australia["calls"].get("generation", 0) == 1, australia
            stream = chat("strict_rejects_streaming", "What is the latest major Go release?", "-stream", stream=True)
            assert stream["status"] == 503 and stream["text"] is None and stream["calls"].get("generation", 0) == 0, stream
            return {"provenance": "bifrost_http_fixture_replay", "scenario_scope": namespace, "passed": True, "rows": trace}
        finally:
            try:
                control(0, scope=None)
            finally:
                clock("reset")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    port = os.getenv("NGINX_PORT") or dotenv_values(ROOT / ".env").get("NGINX_PORT") or "8080"
    parser.add_argument("--gateway", default=f"http://localhost:{port}")
    parser.add_argument("--fixture", default="http://127.0.0.1:8099")
    parser.add_argument("--console", help="Console origin when running the verifier separately")
    parser.add_argument("--password-file", type=Path, default=ROOT / ".admin-password")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.gateway, args.fixture, args.password_file.read_text(encoding="utf-8").strip(), args.console)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
