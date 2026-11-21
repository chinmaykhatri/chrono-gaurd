# ChronoGuard evaluation methodology

## Release evidence replay

Run `python eval/run_eval.py --output release-replay-report.json` from the application directory. The Evaluation Lab uses the same replay model. Every aggregate is derived from the emitted request rows. The historical FreshQA and StaleBench aggregate artifacts are illustrative and excluded.

The fixture freezes the Go release announcements and scopes Node.js to even-numbered major releases. Each timeline runs a fixed synthetic traffic schedule with separate cache routes for the release question and the release-plus-static-control question. Provider awareness of the change is deliberately delayed by 36 hours. Release checks cost two configured units, and the static arithmetic control costs zero. The result depends on these assumptions. [Go 1.24 announcement](https://go.dev/blog/go1.24) · [Go 1.25 announcement](https://go.dev/blog/go1.25) · [Node.js 22 announcement](https://nodejs.org/en/blog/release/v22.0.0) · [Node.js 24 announcement](https://nodejs.org/en/blog/release/v24.0.0)

Eight variants receive the same requests. Cache-only uses scripted provider values. The fixed-TTL variants verify an answer when it is fetched or refreshed, then reuse it until expiry. Always-verify reads the release snapshot on every dynamic claim. The claim ledger reads only due facts and reuses evidence across routes. Snapshot lookups are controlled oracle decisions. The replay does not estimate judge error.

| Measure | Computed from |
|---|---|
| Stale exposures per 1,000 eligible hits | Served values compared with the effective-time release label, among actual replay hits |
| Credits per 1,000 requests | Configured units summed over executed evidence checks |
| Repairs and false corrections | Candidate value, returned value, and known snapshot |
| Provider calls | Simulated generation on misses and retries |
| p50, p95, and p99 | Local replay CPU time by hit, miss, and repair path |

The JSON records the dataset hash and each item’s request timestamp, expected values, returned values, executed evidence lookups, digests and costs. Use the cache-impact graph to compare cost and stale exposures. Read the eligible-hit denominator alongside each point because TTLs alter the hit population.

## Public gateway smoke test

Run `scripts/release_demo.py` after starting the replay stack. It reports real client latency and calls to the local fixture for each scripted scenario. Use its trace to prove dispatch, exact eviction, shared fact invalidation, and failure behavior. It samples one lifecycle and supplies no production percentile.

For a live performance submission, repeat the benchmark on an entity-held-out, independently labeled corpus and capture real generation, embedding, judge, and Tavily spans. Record engine/model versions, the exact gateway build, warm-up, repeated batches, credit usage, raw denominators and uncertainty. Export calibration only when it has been computed from measured probabilities and independent labels.

