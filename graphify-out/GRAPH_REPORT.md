# Graph Report - Chrono-gaurd  (2026-11-21)

## Corpus Check
- 144 files · ~99,209 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 48 file(s) not represented in the graph (top: (none) 40, .lock 2, .css 2)

## Summary
- 1437 nodes · 3231 edges · 112 communities (78 shown, 34 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 156 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7fa4ef74`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ui.tsx
- verify.py
- create_app
- ChronoGuard — Claude Code Project Instructions
- package.json
- Phase 1: Verifier Core Pipeline
- github.com/maximhq/bifrost/core/schemas.BifrostContext
- runtime.go
- redis
- test_pipeline.py
- main.py
- security.py
- testing.T
- Runtime
- guard.go
- Repository
- environment
- Plugin
- pathlib
- feature_weights
- replay
- compilerOptions
- chronoguard
- db.py
- lenient
- prepare.py
- release_fixture.py
- Implementation status
- EvalService
- nginx
- release_demo.py
- Buckets
- ChronoGuard Technical Spikes & Gateway Interoperability Report
- tavily
- depends_on
- postgres
- steps
- os
- services
- news_events
- org_people
- pricing_plans
- regulation_policy
- slow_facts
- software_versions
- healthcheck
- classes
- redis
- ChronoGuard architecture
- Settings
- Security decisions and review scope
- llm
- telemetry
- realtime
- datetime
- clients.py
- weights
- 00-cover-and-conventions.md
- 01-product-requirements-document.md
- 02-website-and-system-working-flow.md
- 03-feature-specifications.md
- 04-technical-requirements-document.md
- 05-implementation-plan.md
- 06-backend-schema.md
- appendix-a-bifrost-tavily-usage-map.md
- test-plan.md
- chronoguard-verifier
- github.com/chronoguard/chronoguard
- main.go
- Clock
- simulate_scheduler.py
- privacy
- standard
- strict
- environment
- dependencies
- scheduler
- mountClock
- build
- urllib_parse
- ledger_totals
- test_gateway_lifecycle.py
- scripts
- migrate
- json
- vite
- cache_row
- context
- reverify_fact_entry
- reissue
- detail_endpoint
- health_state
- degrade
- stream

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 85 edges
2. `Verdict` - 47 edges
3. `Verifier` - 42 edges
4. `key()` - 41 edges
5. `Category` - 40 edges
6. `digest()` - 36 edges
7. `Claim` - 34 edges
8. `display()` - 29 edges
9. `App()` - 28 edges
10. `environment` - 25 edges

## Surprising Connections (you probably didn't know these)
- `f) Failure Tolerance Matrix (Empirical Pytest Output)` --references--> `DependencyUnavailable`  [INFERRED]
  docs/audit.md → chronoguard/verifier/app/clients.py
- `Task 2: Verifier API Contracts & Endpoints (`/internal/v1/record-hit` & `/api/v1/roi`)` --references--> `playground_chat()`  [INFERRED]
  docs/superpowers/plans/2026-11-19-feature-a-shadow-roi.md → chronoguard/verifier/app/main.py
- `Task 3: Bifrost Go Plugin Shadow Mode` --references--> `State`  [INFERRED]
  docs/superpowers/plans/2026-11-19-feature-a-shadow-roi.md → chronoguard/bifrost/plugins/chronoguard/internal/runtime/runtime.go
- `d) Console Endpoints & Metric Sources` --references--> `fact_key()`  [INFERRED]
  docs/audit.md → chronoguard/verifier/app/pipeline/normalize.py
- `Task 1: Database Migration & Configuration Flag` --references--> `Ingest`  [INFERRED]
  docs/superpowers/plans/2026-11-19-feature-a-shadow-roi.md → chronoguard/verifier/app/schemas/contracts.py

## Import Cycles
- None detected.

## Communities (112 total, 34 thin omitted)

### Community 0 - "ui.tsx"
Cohesion: 0.08
Nodes (99): api(), ApiError, asRecord(), asRows(), csvCell(), display(), download(), downloadCsv() (+91 more)

### Community 1 - "verify.py"
Cohesion: 0.06
Nodes (61): clean_text(), cache_evict(), system_probe(), fact_key(), skip_reason(), slug(), default_lambda_for_class(), estimate_lambda() (+53 more)

### Community 2 - "create_app"
Cohesion: 0.08
Nodes (7): create_app(), auth_login(), auth_logout(), budget(), playground_chat(), record_hit_endpoint(), update_policy()

### Community 3 - "ChronoGuard — Claude Code Project Instructions"
Cohesion: 0.05
Nodes (38): 10. Hackathon priorities, 11. Demo narrative, 12. Engineering workflow for Claude Code, 13. Definition of done, 1. Product definition, 2. Required technology roles, 3. Architecture and request lifecycle, 4. Claim model and freshness policy (+30 more)

### Community 4 - "package.json"
Cohesion: 0.11
Nodes (23): devDependencies, jsdom@^27.0.0, @testing-library/react@^16.3.0, @testing-library/user-event@^14.6.1, @types/react@^18.3.0, @types/react-dom@^18.3.0, @types/three@0.187.0, typescript@^5.9.0 (+15 more)

### Community 5 - "Phase 1: Verifier Core Pipeline"
Cohesion: 0.06
Nodes (33): ChronoGuard Implementation Plan, Phase 0: Infrastructure & Scaffolding, Phase 1: Verifier Core Pipeline, Phase 2: Bifrost Integration (Go Plugins), Phase 3: Cache Loop, Phase 4: Console (React), Phase 5: Evaluation & Polish, Task 10: Freshness Scoring (+25 more)

### Community 6 - "github.com/maximhq/bifrost/core/schemas.BifrostContext"
Cohesion: 0.15
Nodes (11): isCacheHit(), Fail(), State, HTTPFail(), NewID(), Payload(), Replace(), SafeAnnotation() (+3 more)

### Community 7 - "runtime.go"
Cohesion: 0.11
Nodes (3): HardTTL(), Replacement, Result

### Community 8 - "redis"
Cohesion: 0.08
Nodes (29): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, REDIS_PASSWORD, REDISCLI_AUTH, interval, retries, test (+21 more)

### Community 9 - "test_pipeline.py"
Cohesion: 0.21
Nodes (17): call(), test_judge_model_down_empirical_behavior(), test_policy_unverifiable_mappings(), test_tavily_down_empirical_behavior(), body(), call(), FakeModels, FakeTavily (+9 more)

### Community 10 - "main.py"
Cohesion: 0.09
Nodes (17): ClockAction, DryRun, Login, Pin, PlaygroundChat, SecurityHeaders, Contract, Extraction (+9 more)

### Community 11 - "security.py"
Cohesion: 0.22
Nodes (5): login(), require_internal(), require_session(), safe_public_url(), Task 2: Verifier API Contracts & Endpoints (`/internal/v1/record-hit` & `/api/v1/roi`)

### Community 12 - "testing.T"
Cohesion: 0.15
Nodes (21): TestBackPluginName(), TestPostLLMHookPassThrough(), TestPreLLMHookWithoutGroundID(), TestPreRequestHookNoOp(), manifestAnnotation(), BenchmarkManifestAnnotation(), TestCacheHitUsesLookupOutcomeInsteadOfEmbeddingMetadata(), TestManifestAnnotation() (+13 more)

### Community 13 - "Runtime"
Cohesion: 0.14
Nodes (12): New(), New(), Manifest, Key(), Get(), Runtime, New(), Client (+4 more)

### Community 14 - "guard.go"
Cohesion: 0.14
Nodes (19): canonicalRelation(), Check(), cleanEntity(), contains(), containsAny(), Decode(), deduplicateAndSort(), equalSets() (+11 more)

### Community 15 - "Repository"
Cohesion: 0.08
Nodes (8): Repository, FakeBuckets, FakeClock, setup_verifier(), Feature A: Shadow Mode and ROI Report Implementation Plan, Task 1: Database Migration & Configuration Flag, Task 4: Console `/roi` Page & Navigation, Task 5: Automated Testing & Evaluation Report

### Community 16 - "environment"
Cohesion: 0.17
Nodes (31): environment, CG_ADMIN_PASSWORD_HASH, CG_ALLOW_SIMULATED_CLOCK, CG_BIFROST_URL, CG_CONSOLE_ORIGIN, CG_DATABASE_URL, CG_DEFAULT_POLICY, CG_DELTA_ENABLED (+23 more)

### Community 17 - "Plugin"
Cohesion: 0.20
Nodes (6): Plugin, extractMessages(), lastUserMessage(), TestClassifyFromLastUserMessage(), TestExtractMessages(), Tenant()

### Community 18 - "pathlib"
Cohesion: 0.20
Nodes (4): main(), main(), main(), main()

### Community 19 - "feature_weights"
Cohesion: 0.25
Nodes (8): agreement, authority, contra, coverage, prior, recency, support, feature_weights

### Community 20 - "replay"
Cohesion: 0.09
Nodes (23): depends_on, environment, volumes, replay, CG_ALLOW_SHADOW_HEADER, CG_ALLOW_SIMULATED_CLOCK, CG_ENVIRONMENT, CG_REPLAY_HOST (+15 more)

### Community 21 - "compilerOptions"
Cohesion: 0.14
Nodes (13): compilerOptions, esModuleInterop, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+5 more)

### Community 22 - "chronoguard"
Cohesion: 0.12
Nodes (15): chronoguard, clock, delta, enabled, guard, kill_switch, plugin_order, policies (+7 more)

### Community 23 - "db.py"
Cohesion: 0.17
Nodes (6): base_columns(), now(), claim_review(), online(), run(), upgrade()

### Community 24 - "lenient"
Cohesion: 0.17
Nodes (12): blocking_budget_ms, evict_below, max_claims_per_response, max_credits_per_response, mode, on_unverifiable, regen_budget_ms, regen_on_stale (+4 more)

### Community 25 - "prepare.py"
Cohesion: 0.47
Nodes (3): build(), prepare(), run()

### Community 26 - "release_fixture.py"
Cohesion: 0.11
Nodes (4): MockLLMHandler, claim(), completion(), Handler

### Community 27 - "Implementation status"
Cohesion: 0.05
Nodes (39): ChronoGuard evaluation methodology, Public gateway smoke test, Release evidence replay, Before presenting, ChronoGuard hackathon demo, Three-minute walkthrough, ChronoGuard, Development checks (+31 more)

### Community 28 - "EvalService"
Cohesion: 0.23
Nodes (5): EvalService, request_trace(), test_eval_service_freshqa_integration(), test_freshqa_dataset_structure(), test_unmeasured_fixture_does_not_publish_metrics()

### Community 29 - "nginx"
Cohesion: 0.18
Nodes (11): condition, condition, bifrost, console, verifier, depends_on, image, ports (+3 more)

### Community 30 - "release_demo.py"
Cohesion: 0.24
Nodes (4): main(), run(), chat(), counters()

### Community 32 - "ChronoGuard Technical Spikes & Gateway Interoperability Report"
Cohesion: 0.15
Nodes (12): ChronoGuard Technical Spikes & Gateway Interoperability Report, Spike 10: Custom Keys in `ExtraFields`, Spike 11: Metrics Exposure, Spike 1: Cache-Hit Metadata Fields, Spike 2: Cache Entry ID vs Request ID, Spike 3: Clear-By-ID Endpoint, Spike 4: `x-bf-cache-ttl` Behavior, Spike 5: Async Cache Write Delay (+4 more)

### Community 33 - "tavily"
Cohesion: 0.22
Nodes (9): tavily, advanced_search, basic_search, extract_per_5_urls, credit_costs, credits_per_hour, extract_timeout_seconds, max_retries (+1 more)

### Community 34 - "depends_on"
Cohesion: 0.18
Nodes (11): depends_on, migrate, redis, weaviate-ready, condition, condition, bifrost, verifier (+3 more)

### Community 35 - "postgres"
Cohesion: 0.29
Nodes (7): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, environment, image, volumes, postgres

### Community 36 - "steps"
Cohesion: 0.07
Nodes (28): run, defaults, runs-on, steps, timeout-minutes, jobs, gateway-replay, name (+20 more)

### Community 38 - "services"
Cohesion: 0.17
Nodes (11): name, services, console, weaviate-ready, volumes, postgres_v2, redis_v2, weaviate_data (+3 more)

### Community 39 - "news_events"
Cohesion: 0.29
Nodes (7): news_events, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 40 - "org_people"
Cohesion: 0.29
Nodes (7): org_people, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 41 - "pricing_plans"
Cohesion: 0.29
Nodes (7): pricing_plans, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 42 - "regulation_policy"
Cohesion: 0.29
Nodes (7): regulation_policy, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 43 - "slow_facts"
Cohesion: 0.29
Nodes (7): slow_facts, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 44 - "software_versions"
Cohesion: 0.29
Nodes (7): software_versions, cacheable, half_life_seconds, interval_max_seconds, interval_min_seconds, salience, soft_ttl_seconds

### Community 45 - "healthcheck"
Cohesion: 0.57
Nodes (8): interval, retries, test, timeout, healthcheck, healthcheck, healthcheck, healthcheck

### Community 46 - "classes"
Cohesion: 0.33
Nodes (6): classes, static, cacheable, half_life_seconds, salience, soft_ttl_seconds

### Community 47 - "redis"
Cohesion: 0.29
Nodes (7): REDIS_PASSWORD, REDISCLI_AUTH, command, environment, image, volumes, redis

### Community 48 - "ChronoGuard architecture"
Cohesion: 0.40
Nodes (4): Cache lifecycle, ChronoGuard architecture, Decisions and tradeoffs, Evidence and claims

### Community 49 - "Settings"
Cohesion: 0.11
Nodes (9): Settings, Database, lifespan(), prune_content(), run_jobs(), client(), guard_client(), app() (+1 more)

### Community 50 - "Security decisions and review scope"
Cohesion: 0.33
Nodes (5): Failure and freshness, Review status, Secrets and deployment, Security decisions and review scope, Trust boundaries

### Community 51 - "llm"
Cohesion: 0.40
Nodes (5): llm, extractor_temperature, judge_temperature, max_claims_per_extraction, tokens_per_hour

### Community 52 - "telemetry"
Cohesion: 0.40
Nodes (5): telemetry, log_level, prometheus_enabled, prometheus_port, structured_logging

### Community 53 - "realtime"
Cohesion: 0.40
Nodes (5): realtime, cacheable, half_life_seconds, salience, soft_ttl_seconds

### Community 54 - "datetime"
Cohesion: 0.29
Nodes (6): main(), run_browser_checks(), points(), run_replay(), snapshot_at(), timestamp()

### Community 55 - "clients.py"
Cohesion: 0.11
Nodes (9): DependencyUnavailable, ModelClient, strict_schema(), walk(), TavilyClient, Evidence, redact_query(), FailingJudgeModels (+1 more)

### Community 56 - "weights"
Cohesion: 0.29
Nodes (7): scoring, bias, weights, confirmed, contradicted, outdated, unverifiable

### Community 68 - "main.go"
Cohesion: 0.25
Nodes (7): main(), round2(), round4(), GuardDataset, GuardPair, GuardReport, PairResult

### Community 69 - "Clock"
Cohesion: 0.52
Nodes (3): Clock, get_clock(), set_clock()

### Community 71 - "privacy"
Cohesion: 0.50
Nodes (4): privacy, redact_pii, retention_days, store_content

### Community 72 - "standard"
Cohesion: 0.17
Nodes (12): standard, blocking_budget_ms, evict_below, max_claims_per_response, max_credits_per_response, mode, on_unverifiable, regen_budget_ms (+4 more)

### Community 73 - "strict"
Cohesion: 0.17
Nodes (12): strict, blocking_budget_ms, evict_below, max_claims_per_response, max_credits_per_response, mode, on_unverifiable, regen_budget_ms (+4 more)

### Community 74 - "environment"
Cohesion: 0.25
Nodes (8): AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED, CLUSTER_HOSTNAME, DEFAULT_VECTORIZER_MODULE, PERSISTENCE_DATA_PATH, weaviate, environment, image, volumes

### Community 75 - "dependencies"
Cohesion: 0.17
Nodes (12): dependencies, @fontsource/instrument-serif@5.3.0, @fontsource-variable/dm-sans@5.3.0, lucide-react@1.77.0, react@^18.3.1, react-dom@^18.3.1, react-router-dom@^7.0.0, three@0.187.0 (+4 more)

### Community 76 - "scheduler"
Cohesion: 0.67
Nodes (3): scheduler, budget_checks_per_hour, mode

### Community 77 - "mountClock"
Cohesion: 0.29
Nodes (10): ClockPose, dialTexture(), mountClock(), disc(), hand(), mount(), render(), resize() (+2 more)

### Community 82 - "build"
Cohesion: 0.33
Nodes (5): build, entitlements, network, services, bifrost

### Community 98 - "ledger_totals"
Cohesion: 0.50
Nodes (5): get_roi(), latency(), percentile(), summary(), window_start()

### Community 99 - "test_gateway_lifecycle.py"
Cohesion: 0.28
Nodes (12): app(), body(), call(), FakeModels, FakeTavily, make_claim(), make_evidence(), test_cache_miss_extraction_and_manifest_indexing() (+4 more)

### Community 100 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, dev, preview, test, typecheck

### Community 101 - "migrate"
Cohesion: 0.33
Nodes (6): postgres, command, depends_on, image, condition, migrate

### Community 102 - "json"
Cohesion: 0.13
Nodes (13): ledger_totals(), test_classes_and_summary(), test_clock_endpoints(), test_eval_datasets_and_runs(), test_healthz(), test_net_savings_requires_prices_for_both_saved_and_spent_work(), test_readyz(), test_system_probe() (+5 more)

### Community 103 - "vite"
Cohesion: 0.40
Nodes (4): vite@^7.0.0, @vitejs/plugin-react@^5.0.0, vite, @vitejs/plugin-react

### Community 104 - "cache_row"
Cohesion: 0.67
Nodes (3): cache_pin(), cache_revalidate(), cache_row()

### Community 105 - "context"
Cohesion: 0.24
Nodes (11): upstream_source, build, additional_contexts, context, dockerfile, build, build, build (+3 more)

### Community 106 - "reverify_fact_entry"
Cohesion: 0.67
Nodes (3): claim_reverify(), fact_reverify(), reverify_fact_entry()

### Community 107 - "reissue"
Cohesion: 0.40
Nodes (5): policy_dry_run(), reissue(), revalidate(), verify_inline(), prompt_class()

### Community 108 - "detail_endpoint"
Cohesion: 0.50
Nodes (3): detail_endpoint(), list_endpoint(), endpoint()

### Community 109 - "health_state"
Cohesion: 0.50
Nodes (4): health_state(), internal_health(), ready(), settings_health()

### Community 110 - "degrade"
Cohesion: 0.67
Nodes (3): degrade, actions, threshold_pct

## Knowledge Gaps
- **2 isolated node(s):** `github.com/chronoguard/chronoguard`, `chronoguard-verifier`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 573 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **34 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Feature A: Shadow Mode and ROI Report Implementation Plan` connect `Repository` to `security.py`, `Runtime`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `create_app()` (e.g. with `lifespan()` and `Category`) actually correct?**
  _`create_app()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `github.com/chronoguard/chronoguard`, `chronoguard-verifier` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `ui.tsx` be split into smaller, more focused modules?**
  _Cohesion score 0.07648483122062384 - nodes in this community are weakly interconnected._
- **Why does `Task 3: Bifrost Go Plugin Shadow Mode` connect `Runtime` to `github.com/maximhq/bifrost/core/schemas.BifrostContext`, `Repository`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `Verdict` (e.g. with `ModelClient` and `status_for()`) actually correct?**
  _`Verdict` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Should `verify.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05729032258064516 - nodes in this community are weakly interconnected._