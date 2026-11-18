# Implementation status

This file records implementation and observed validation separately. Specifications are not evidence that a feature works.

## Work roles and execution loop

Six roles rotate through three concurrent sub-agent slots, with the coordinating agent integrating the work:

1. Gateway: Bifrost source pin, S1–S5/S7, plugins and cache decisions.
2. Verifier: S6/S8, persistence, evidence pipeline, coordination and API.
3. Console: authenticated operator UI, real API integration and accessibility.
4. Evaluation: datasets, baselines, metrics, calibration and benchmarks.
5. Security and reliability: adversarial review, failure paths and concurrency.
6. Release and integration: reproducible deployment, end-to-end tests and documentation.

As of this update, the three registered swarm worktrees (`swarm-datamodels`, `swarm-pipeline`, `swarm-scaffold`) contain no commits and no modified files; their `chronoguard/` directories hold only the original `.gitkeep` scaffold. Their assigned work has not been integrated. The coordinating agent therefore implemented the verifier slice and console foundation directly in the main checkout.

## Initial inspection

- Original repository contained specifications and empty application directories.
- Go 1.26.1 (toolchain auto-upgrades to the module's 1.27.3), Node 22.18, uv 0.11 and Docker 29 are available.
- Docker data services (Postgres 16, Redis 7) start from `deploy/compose.data.yml`.
- Tavily and Anthropic credentials are present in the local `.env`; extractor/judge model ids are empty.
- No Bifrost gateway process was running. Another unrelated service occupies port 8000; the local verifier was run on 8010 for console checks.

## Implemented in this slice

### Verifier

- `app/pipeline/verify.py`: claim extraction through the configured model, atomic fact-key normalisation, ledger hits, singleflight locking, Tavily retrieval, judge adjudication, the three-condition evidence/invalidation rule, freshness and support-confidence scoring, adaptive intervals, claim/fact/verification/evidence persistence, Redis manifests and revalidation.
- `app/pipeline/budget.py`: tenant-scoped, refilling Tavily-credit and LLM-token buckets using Redis WATCH/MULTI.
- `app/pipeline/triage.py`: prompt classification, per-class Tavily profiles, claim priority.
- `POST /internal/v1/verify-inline` now runs the pipeline instead of returning `verification_pipeline_not_ready`.
- `POST /internal/v1/revalidate` now revalidates due claims and rewrites the manifest with a new revision.
- Background workers consume `verification_jobs`; inline verification does not enqueue a duplicate job.
- SQLAlchemy async now installs `greenlet` through the `sqlalchemy[asyncio]` extra; the service previously could not start.

### Console API

- `/api/v1/summary`, `/classes`, `/latency`, `/settings/bifrost`, `/settings/health` (structured connection checks), `/policies/dry-run`.
- Cache actions: revalidate, evict (manifest-level), pin.
- Claim actions: revalidate, mark reviewed. Fact action: re-verify.
- `/api/v1/playground/chat` proxies Bifrost, returns manifest annotations on cache hits without re-ingesting, and runs inline verification for strict requests.
- `/api/v1/models` asks Bifrost when no model ids are configured.
- Evaluation dataset/run lists return an honest empty registry (`available: false`); the runner is not implemented.

### Console

- Added the missing `src/styles.css`. The console previously imported a stylesheet that did not exist and could not build. The stylesheet implements the documented operator-console layout: sidebar, top bar, six KPI cells, hairline tables, status language, score bars, evidence cards, Playground split view, login and responsive rules.
- Fixed Playground's semantic-cache checkbox inheriting a 136px input width.
- Fixed clock requests to send the backend's `seconds`/`timestamp` field names.
- `vite.config.ts` accepts `VITE_API_TARGET` so the console can target a verifier that is not on port 8000.

## Observed validation

| Check | Result | Notes |
| --- | --- | --- |
| `uv run pytest -q` | 5 passed | SQLite + fakeredis, scripted model/Tavily clients. Covers confirmed+ledger reuse, unmet invalidation rule, budget refusal, singleflight coalescing, revalidation revision. |
| `cd console && npm run build` | passed | `tsc --noEmit` and Vite production build, 45 modules. |
| `cd bifrost/plugins/chronoguard && go build ./... && go test ./...` | passed | Existing classify/decide tests. Plugin entrypoints are still absent. |
| Live verifier + console | started | Postgres/Redis compose data services, Alembic migration, uvicorn on 8010, Vite on 5173, authenticated login, Settings/summary/classes endpoints exercised. |
| Visual inspection | screenshots | Overview, Playground, Cache explorer and Settings rendered at 1440px; login and empty states checked. |

## Gates

| Gate | Status | Evidence required |
| --- | --- | --- |
| G1 integration spikes | In progress | Pinned Bifrost, actual hook/cache/invalidation behavior, Tavily probe. No cg-front/cg-back entrypoints or gateway run yet. |
| M1 walking skeleton | Partial | Verifier creates and persists requests/annotations; no gateway request path yet. |
| M2 inline verification | Partial | Strict inline pipeline implemented and tested with scripted dependencies; no live model/Tavily run recorded. |
| M3 cache loop | Pending | Revalidation and exact eviction exist only at manifest level; Bifrost cache invalidation and regeneration are not wired. |
| M4 evaluation | Pending | No dataset, runner or report. |
| G6 release | Pending | CI, integration/security suite, deployment validation. |

## Security decisions

- Strict policy must never release known-stale content on failure or streaming paths; stricter guidance in claude.md resolves conflicting fallback prose in the feature pack.
- Externally supplied internal-control headers must not grant trusted internal privileges.
- All lookup, manifest, lock and cache associations require an explicit tenant scope.
- Missing evidence or unavailable dependencies must never generate a fresh verdict.
- Keys remain in environment/ignored secret files; web content and model output remain untrusted data.

## Known limitations

- No live Bifrost integration: the documented `cg-front`/`cg-back` plugin entrypoints and HTTP hooks do not exist, so no gateway request reaches the verifier yet.
- Cache eviction from the console marks the ChronoGuard manifest evicted; it does not call Bifrost's exact-entry deletion.
- Regeneration, cascade across entries and streaming annotations are not implemented.
- The Evaluation Lab has no dataset storage or runner; the UI shows an honest empty registry.
- The pipeline has only been exercised with scripted clients, not a live extractor/judge or live Tavily response.
