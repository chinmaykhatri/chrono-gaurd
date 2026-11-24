# ChronoGuard

A release changes overnight. Two cached answers still recommend the old version. ChronoGuard checks their shared fact once, marks the affected entries stale and verifies the replacement before the gateway returns it.

[Watch the 24-second operator demo](chronoguard/docs/release-demo.webm) · [Inspect the gateway trace](chronoguard/eval/reports/gateway-lifecycle.json) · [View CI runs](https://github.com/chinmaykhatri/chrono-gaurd/actions/workflows/chronoguard-replay.yml)

## Run the demo

From `chronoguard/`, run the following with Docker, Git and uv installed.

```sh
uv run --project verifier python scripts/bootstrap.py
docker compose -f docker-compose.yml -f deploy/compose.replay.yml -p chronoguard-replay up --build -d --wait
uv run --project verifier python scripts/release_demo.py --output release-proof.json
```

Open the console at `http://localhost:8080` and sign in with the generated local `.admin-password`. The run exercises Bifrost, the verifier, the vector cache, PostgreSQL and Redis. The provider, search results and clock are controlled so a judge can repeat the same release change without credentials. The second identical request after eviction verifies that the gateway actually cleared the old cache entry. [Setup and alternate ports](chronoguard/README.md) · [Demonstration steps](chronoguard/docs/demo-script.md)

## What the measurements say

| Question | Observed result | Evidence |
| --- | --- | --- |
| Does repair cross the gateway boundary? | The HTTP client received Go 1.25 after one due search. A related entry became stale. A simulated provider outage returned 503 with no answer text. | [11 gateway cases](chronoguard/eval/reports/gateway-lifecycle.json) |
| What does serving a warm answer cost locally? | Across five alternating trials, 100 direct hits generated zero new answers. Cache-disabled requests generated 100. Client p50/p95/p99 were 4.53/6.28/6.97 ms for hits and 40.83/52.52/77.99 ms with caching disabled. The provider runs locally. | [200 timed requests](chronoguard/eval/reports/gateway-latency.json) |
| Does adaptive scheduling beat TTLs on other releases? | On 8,760 simulated requests with 2025 PyPI upload dates as ground truth, the scheduler matched a 48-hour TTL at 97 stale answers and 1,098 checks. Under the tighter weekly budget it served 507 stale answers for 309 checks. A seven-day TTL served 397 for 318 checks. | [Held-out timeline](chronoguard/eval/reports/publisher-timeline.json) · [Request-level CSV](chronoguard/eval/reports/publisher-timeline.csv.gz) |
| Can the heuristic distinguish paraphrases reliably? | The Go guard classified 60/100 external PAWS-Wiki pairs correctly. It let 17 differing pairs through and rejected 23 valid paraphrases. | [Independent guard results](chronoguard/eval/reports/paws-held-out.json) |
| How well does a real local model verify claims? | On a 24-item WiCE sample, Qwen2.5 1.5B confirmed 3/16 statements with incomplete support. The invalidation rule evicted 0/8 fully supported statements. Exact-span extraction recovered 10/24 reference spans with 10 predictions. Two judge outputs failed validation. | [Per-item model results](chronoguard/eval/reports/wice-local.json) |
| Can a model incorporate a known correction? | Given six archival PyPI updates, local generation returned the expected version in 6/6 answers with zero extra version strings. This measures version accuracy with evidence supplied. | [Generated answers and sources](chronoguard/eval/reports/grounded-repairs.json) |

The 4,672-row Go/Node policy replay uses scripted traffic and a delayed provider. Accuracy on production traffic, throughput under concurrency and billed provider costs still need live trials. [Methods and reproduction](chronoguard/docs/benchmark.md)

The optional FreeModel profile has live Bifrost chat, claim extraction and evidence judging with `claude-opus-5`. It uses 384-dimensional MiniLM embeddings from local Ollama and needs a separate Tavily key for live search. [Provider setup](chronoguard/README.md#use-the-freemodel-provider) · [Observed provider results](chronoguard/eval/reports/freemodel-live.json)

## Operate and review

The Go gateway decides whether to serve, recheck or replace each cached answer. The Python verifier stores claim evidence and coordinates updates across entries. The operator console traces those decisions back to the evidence. [Current architecture](chronoguard/docs/architecture.md) · [Review findings and remaining work](chronoguard/docs/review-findings.md)

The local Compose setup runs the full stack with either OpenAI or FreeModel. Both live profiles use Tavily for evidence retrieval. The hosted console/verifier blueprint needs a separately reachable Bifrost gateway and Redis, a password hash and an exact HTTPS console origin. The `docs/` directory at repository root contains design specifications and historical implementation notes.
