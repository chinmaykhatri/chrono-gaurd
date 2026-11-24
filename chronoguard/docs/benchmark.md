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


## Independent experiments and measured gateway latency

The publisher comparison uses the first published stable distribution for each version of six PyPI packages. The frozen input retains one version before training and every relevant upload through 2025. The 2024 observations determine rate estimates and the 2025 labels are held out. All policies receive the same six-hour query stream and have perfect access to the registry when checking. The weekly and daily budgets show how the implementation behaves at different credit limits. [PyPI JSON API](https://docs.pypi.org/api/json/) · [Publisher data](../eval/dataset/pypi-release-history.json)

The semantic test uses the first 100 published PAWS-Wiki labeled-final test pairs. The model experiment selects eight WiCE subclaims per label by a fixed hash of the source ID. The judge receives the six source sentences with the highest lexical overlap. Annotator evidence indices and labels are withheld. A separate paired-text test measures exact extracted span recovery. Failed calls and abstentions remain in the output. A local Qwen2.5 1.5B model ran using the application's ModelClient. Repeated decoding on other hardware may differ. [PAWS authors](https://github.com/google-research-datasets/paws) · [WiCE authors](https://github.com/ryokamoi/wice)

From the application directory, run the following. The local model trial needs Ollama running with the specified model downloaded. The latency command uses only a quiet, isolated replay stack. Warm-ups are excluded and the checker confirms each hit and upstream generation using fixture counters. The captured latency report gives observed end-to-end HTTP times on one machine. It measures sequential behavior.

```sh
uv run --project verifier python eval/publisher_timeline.py --output publisher-timeline.json
uv run --project verifier python eval/independent.py guard --output paws.json
ollama pull qwen2.5:1.5b
uv run --project verifier python eval/independent.py model --output wice.json
uv run --project verifier python eval/independent.py repairs --output repairs.json
uv run --project verifier python scripts/gateway_benchmark.py --output gateway-latency.json
```

Use `--refresh` with the publisher script to rebuild the input from the registry. Its hash will change if a publisher edits or removes archival material. [Raw reports](../eval/reports/)

