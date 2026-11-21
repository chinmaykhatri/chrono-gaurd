# ChronoGuard

ChronoGuard adds a freshness policy to the Bifrost semantic cache. It extracts public factual claims from model answers, gives each claim a verification window, and stores shared evidence in a fact ledger. A release change can mark every cached answer that mentions the old version stale.

The gateway makes the delivery decision. FastAPI verifies claims and updates the evidence and manifest records. Redis holds policies, clocks, the hot manifest and coordination state. PostgreSQL stores the verification trail. The React console shows the gateway outcome, supporting sources, and evaluation traces.

## Run the release replay

Run these commands from this directory with Docker Desktop or Docker Engine, Git, and uv available. The replay uses a local fixture provider and search service. It needs no model or Tavily API key.

```sh
uv run --project verifier python scripts/bootstrap.py
docker compose -f docker-compose.yml -f deploy/compose.replay.yml -p chronoguard-replay up --build -d --wait
uv run --project verifier python scripts/release_demo.py --output release-proof.json
```

Open [the console](http://localhost:8080) and use the generated password in `.admin-password`. The first gateway build fetches the pinned Bifrost revision, applies the integration patch, and compiles the embedded plugins. The replay clock and fixture are only for this local stack.

If port 8080 is occupied, set `NGINX_PORT=18080` and `CG_CONSOLE_ORIGIN=http://localhost:18080` in your shell before starting Compose and the demo. Open the console on the selected port. Each replay scopes its fixture facts to a fresh run, so you can repeat the scenario against the same database and keep earlier results.

If the Docker builder cannot complete the source download, pass it an archive of the same pinned revision. In PowerShell, run these commands before retrying Compose.

```powershell
$sourceArchive = Join-Path $env:TEMP 'chronoguard-pinned-source'
python bifrost/prepare.py --archive $sourceArchive
$env:CG_BIFROST_SOURCE_CONTEXT = $sourceArchive
```

If Docker can fetch the source but its build network times out contacting the Go module proxy, the optional build override lets the gateway compiler use the host network.

```sh
docker compose -f docker-compose.yml -f deploy/compose.replay.yml -f deploy/compose.build-host-network.yml -p chronoguard-replay up --build -d --wait
```

The demo asserts two cache entries sharing a release fact, a fresh semantic hit, one due fact lookup, a grounded replacement, strict refusal during an injected provider outage, and a subsequent miss after exact eviction. Bifrost, PostgreSQL, Redis, and Weaviate run normally in this replay. The generations, embeddings, evidence responses, and clock are controlled.

For live integrations, set `OPENAI_API_KEY` and `TAVILY_API_KEY` in the generated `.env` and start the base stack with `docker compose up --build -d --wait`. The base stack binds the console and gateway to loopback. Keep the replay and live runs in distinct Compose projects.

## Evaluate the policy

```sh
python eval/run_eval.py --output release-replay-report.json
```

The Evaluation Lab and CLI replay a frozen Go and Node.js release timeline. They compare cache-only, five TTLs, always verify, and a claim ledger. The export includes returned and expected values, cache outcomes, evidence digests, credit units, provider-call counts, and local replay timings. [Benchmark methodology](docs/benchmark.md)

## Request behavior

| Path | Gateway behavior |
|---|---|
| Fresh hit | Checks the cached text against the stored manifest. No new factual search, generation, extraction, or judge call. Semantic lookup may call an embedding model. |
| Due hit | Checks due claims and reuses supported facts across matching entries. Strict policy waits for the result. |
| Known stale hit | Rejects the old answer, clears the exact Bifrost entry, retries with evidence, and verifies the replacement before serving it. Cascade marks related manifests stale. |
| Guard rejects a candidate | Issues a cache-disabled provider call with the incoming conversation and withholds the cached answer. |
| Evidence or provider failure | Strict policy returns a verification error. Standard can serve annotated uncertainty on eligible fail-open paths. |
| Strict streaming | The gateway rejects this mode before sending answer tokens. |
| Shadow | Records what the gateway would decide using available manifests. Per-request shadow headers require explicit gateway configuration. |

The replay targets non-streamed text chat. Strict mode attempts a grounded retry on a known-stale initial answer when evidence is available and withholds unverified text. The guard remains a heuristic with limited held-out coverage. Set `CG_DELTA_ENABLED=true` and `CG_DELTA_SOURCE_URLS` to a JSON list of approved authoritative HTTPS URLs to opt in to delta revalidation. Set `CG_SCHEDULER_MODE=optimal` for the bounded due-on-access refresh allocator. The replay report covers policy behavior under controlled assumptions. Live accuracy, throughput, and savings require a separate measurement.

## Development checks

```sh
python bifrost/prepare.py
cd bifrost/plugins/chronoguard && go test ./...
```

From this directory, run `uv run --project verifier pytest verifier/tests -q` and run `npm ci`, `npm run build`, and `npm test` in `console`. Use [the demo script](docs/demo-script.md) for public endpoint verification.

With the replay stack running, these commands also exercise the signed-in console in Chromium. The browser check opens all ten pages on desktop and mobile, saves an existing policy, verifies a fact, exports the evaluation and tests keyboard, drag, scroll and reduced-motion behavior. Pass `--gateway http://localhost:18080` if you selected port 18080.

```sh
uv run --with playwright==1.60.0 python -m playwright install chromium
uv run --with playwright==1.60.0 python scripts/console_smoke.py --output browser-proof.json
```

ChronoGuard integrates [Bifrost](https://github.com/maximhq/bifrost) and [Tavily](https://tavily.com). The historical FreshQA-derived and StaleBench label fixtures remain available for future measured evaluation.

