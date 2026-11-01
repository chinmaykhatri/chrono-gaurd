# Document 4: Technical Requirements Document (TRD)
4.1 Scope and design goals
This document defines architecture, algorithms, contracts, performance budgets,
reliability, security, testing and deployment for ChronoGuard. Design goals in priority
order:
1. Never harm the gateway: isolation, timeouts, fail-open defaults.
2. Minimal hot-path work: classification by patterns, decisions from Redis, no database
calls.
3. Fact-level sharing: one verification serves every answer that mentions the fact.
4. Explainability: every decision has reason codes and evidence.
5. Measurability: every claim we make in the demo is backed by a reproducible run.
6. Hackathon feasibility: thin vertical slices, and a Plan B for every risky assumption.
4.2 Architecture overview
Component
Technology
Responsibilities
State
cg-front
Go, in-tree
Bifrost plugin
HTTP pre and post hooks,
prompt classifier, policy
resolution, cache headers,
decision engine on hits,
ingestion queue, annotations
and headers
In-process queue and
policy cache. Reads
Redis
cg-back
Go, same
module
Grounding injection for
regeneration, origin tagging
Reads Redis
Verifier
Python 3.12,
FastAPI
Claim extraction,
classification, ledger, triage,
Tavily, judge, scoring,
manifests, cascade,
regeneration, eval runner,
REST and SSE
Postgres and Redis
Console
React 18,
TypeScript, Vite
All pages in Document 2
None
Principle: the hot path reads only Redis. The plugin never calls Postgres. Postgres feeds
the console and the evaluation.
4.3 Technology stack
Component
Technology
Responsibilities
State
Redis 7
Store
Manifests, ledger mirror,
locks, streams, clock,
budgets, pub/sub
Volatile with AOF
Postgres 16
Store
System of record for audit,
analytics, evaluation
Durable
Weaviate
Store owned by
Bifrost
Semantic cache vectors
[verify supported stores]
Bifrost
Tavily
SaaS
Search and Extract
External
Layer
Choice
Pin and rationale
Gateway
Bifrost (fork)
Pin one release on Day 0. It is the
target of PS 04
Go
Version in Bifrost's go.mod
In-tree build avoids shared-object
version mismatches
Verifier
libraries
FastAPI, Uvicorn, httpx, pydantic v2,
SQLAlchemy 2 with asyncpg,
Alembic, redis-py (asyncio),
tenacity, orjson, rapidfuzz, scikit-
learn, numpy, structlog,
prometheus-client
Pin in a lockfile. Fast development
and ML tooling
Console
React 18, TypeScript, Vite, Tailwind,
TanStack Query, Recharts
Fast to build, SSE-friendly
Data
Postgres 16, Redis 7
Durable plus fast hot path
Infra
Docker Compose, optional
Prometheus and Grafana
One-command start
4.4 Bifrost integration design
4.4.1 Plugin sandwich and ordering
cg-front is registered before semantic_cache and cg-back after it. Pre-hooks run in
registration order and post-hooks run in reverse, so cg-front sees cache hits on the way
out and cg-back runs only when the provider is really called.
plugins:
  - name: chronoguard_front
    enabled: true
    config: {redis_url: redis://redis:6379/0, verifier_url: 
http://verifier:8088, config_file: /etc/chronoguard.yaml}
  - name: semantic_cache
    enabled: true
    config: {existing cache configuration}
  - name: chronoguard_back
    enabled: true
    config: {redis_url: redis://redis:6379/0}
Ordering semantics (array order, or placement and order fields in newer config schemas)
[verify].
Layer
Choice
Pin and rationale
Testing
Go test, pytest with respx and
pytest-asyncio, k6 or vegeta,
Playwright smoke
Contract tests with a mocked Tavily
LLM access
Bifrost's OpenAI-compatible API for
extractor, judge and regeneration
Dogfooding, per-key budgets, one
place for model routing
Hook
Plugin
Responsibility
HTTPTransportPreHook
front
Parse body, classify prompt, resolve
policy, set cache headers or bypass,
stamp state, kill switch
PreLLMHook
front
Skip internal requests, start timers,
create request id
4.4.2 Request-scoped state
Context keys: cg.request_id, cg.policy_id, cg.prompt_class, cg.skip, cg.t0, cg.cache_hit,
cg.cache_id, cg.decision, cg.annotation. State must travel from the HTTP hooks to the LLM
hooks through the Bifrost context [verify propagation].
4.4.3 In-tree build recipe
1. Fork maximhq/bifrost at the pinned tag.
2. Add plugins/chronoguard (both plugins in one Go module with shared internal
packages: classify, manifest, decide, annotate, clock, verifierclient).
3. Register chronoguard_front and chronoguard_back in the HTTP transport's plugin
loader, next to the built-in plugins [verify location].
4. Build the Docker image from the repository's Dockerfile and mount config.json.
5. Optional path: a shared-object build with go build -buildmode=plugin using exactly
Bifrost's Go version and dependency versions.
4.4.4 Failure containment
Every hook has a deferred recover(), a context deadline and a metric.
Circuit breakers wrap Redis and the Verifier client. The hot path never waits on the
Verifier except in explicit blocking modes with deadlines.
Hook
Plugin
Responsibility
PreLLMHook
back
Inject grounding when x-cg-ground-id is
present
PostLLMHook
back
Tag origin (provider or regenerated)
PostLLMHook
front
Miss: ingest (async) or verify inline
(strict). Hit: manifest lookup, decision,
annotations, regeneration replacement
HTTPTransportPostHook
front
Add x-cg-* headers from request state
HTTPTransportStreamChunkHook
front
Record response id. P2: buffering
PreRequestHook (routing phase)
none in
MVP
Reserved for freshness-aware routing in
v1
Cleanup
both
Drain queues, close Redis
chronoguard_unverifiable errors set AllowFallbacks=false so Bifrost does not retry
another provider.
Global enabled flag and x-cg-mode: off bypass everything.
4.5 Algorithms and decision logic
4.5.1 Claim extraction contract
Claim:
  text: string              # exact span copied from the response
  span: [start, end]        # character offsets, optional
  claim_type: fact | opinion | procedure | definition | personal
  entity: string
  entity_type: org | person_public | product | software | law | place | event 
| other
  attribute: string         # attribute vocabulary key or other:slug
  stated_value: string
  class_key: static | slow_facts | org_people | software_versions | 
pricing_plans | regulation_policy | news_events | realtime
  importance: number 0..1   # central to the answer = high
  as_of_hint: date | null   # only if the text states a date
  official_domain_hint: string | null
Prompt rules: temperature 0, JSON-schema output, only checkable statements about the
world, one entity and one attribute per claim, copy the span exactly, never invent a value,
flag personal data, maximum 25 claims.
4.5.2 Volatility classes (final defaults)
Class
Examples
Half-
life
Soft
TTL
Interval min
to max
Salience
Cacheable
static
Math, definitions, settled
history
none
none
never
rechecked
0
yes
slow_facts
Geography, institutions,
long-lived statistics
365 d
90 d
30 d to 180 d
0.4
yes
org_people
CEOs, founders, team,
headcount
90 d
21 d
7 d to 60 d
0.8
yes
software_versions
Latest versions,
deprecations, API
signatures, model availability
21 d
7 d
2 d to 30 d
1.0
yes
4.5.3 Staleness prior and as-of semantics
The as-of date is what the claim reflects, not when the answer was generated.
Provider-generated claim: as_of = max(model knowledge cutoff, as_of_hint). The
cutoff comes from model_profiles. Unknown models default to today minus 18 months.
Regenerated claim: as_of = date of the evidence used.
Verified fact: as_of = last_verified_at.
age = now() - as_of. P_stale = 1 - 2^(-age / half_life), clamped to 0.02 to 0.98 (static is 0).
Example: a software_versions claim from a model whose cutoff is 270 days old has age
270 d against a 21 d half-life, so P_stale is clamped to 0.98. A slow_facts claim with the
same age has P_stale = 1 - 2^(-270/365) = 0.40.
4.5.4 best_before and hard TTL
fact.fresh_until = last_verified_at + interval_seconds. The initial interval is the class
soft TTL.
entry.best_before = minimum of fresh_until over non-static claims (null if none).
Hard TTL set at request time (F-02) = clamp(8 x soft TTL of the prompt class, 1 h, 30 d).
If the hard TTL expires first, Bifrost drops the entry. That is harmless.
At lookup, best_before in the past means due.
4.5.5 Triage priority and budgets
priority = P_stale * salience * importance * (1 + ln(1 + hits_24h)) / 
cost_units
cost_units = 1 (basic search) or 2 (advanced) + 0.4 if Extract is planned
Class
Examples
Half-
life
Soft
TTL
Interval min
to max
Salience
Cacheable
pricing_plans
Prices, tiers, quotas, rate
limits
14 d
3 d
12 h to 14 d
1.0
yes
regulation_policy
Laws, tax rates, deadlines,
compliance rules
60 d
14 d
3 d to 45 d
1.0
yes
news_events
Recent events, launches,
outcomes
4 d
1 d
6 h to 3 d
0.7
yes
realtime
Asset prices, scores,
weather, FX
15 min
0
n/a
1.0
no
(bypass)
Per response: sort by priority and take claims until max_claims_per_response or
max_credits_per_response. Global token buckets: Tavily credits per hour (default 300)
and LLM tokens per hour (default 400,000). Degrade ladder below 20 percent of a bucket:
advanced to basic, drop Extract, raise the priority cutoff. At zero: mark remaining claims
unverifiable with reason budget.
4.5.6 Query synthesis and Tavily profiles
Templates per class, at most 2 queries per fact: latest stable version of {entity}; {entity}
{plan} pricing per month; current {attribute} of {entity}; {entity} {attribute}
announcement. An LLM rewrite is used only when the entity is ambiguous.
Credit constants (config, confirm against current Tavily pricing [verify]): basic search 1,
advanced search 2, Extract 1 per 5 URLs (basic depth).
Class
topic
search_depth
Time filter
Domains
Extract
max_results
slow_facts
general
basic
none
none
no
5
org_people
general,
plus a
news
query
basic
news query:
time_range
month
none
no
5
software_versions
general
advanced
none
official hint
and tier 1
top tier-
1 URL
5
pricing_plans
general
advanced
none
official hint
pricing
page
5
regulation_policy
general
advanced
start_date 12
months back
official or
government
hint
yes
5
news_events
news
basic
time_range
week, widen to
month if empty
none
no
6
realtime
finance or
news
basic
day
none
no
5
4.5.7 Evidence normalization and authority tiers
Normalize each result: canonical URL, domain, tier from source_authority, a snippet
window of at most 600 characters around the attribute mention, date from
published_date else a pattern search in the content else null. Dedupe by content hash.
Keep the top 6 ordered by tier, then Tavily score, then recency.
4.5.8 Judge contract
Input:
  claim: {text, stated_value, as_of}
  evidence: [{id, domain, tier, date, snippet}]   # inside delimiters, 
labeled as data
Output:
  verdict: confirmed | outdated | contradicted | unverifiable
  corrected_value: string | null
  confidence: number 0..1
  support_ids: [id]
  contradict_ids: [id]
  as_of_note: string
  rationale: string         # at most 280 characters
Cascade: the primary model first. Escalate once to the stronger model when confidence is
under 0.6, or the verdict is unverifiable with at least 3 relevant items.
4.5.9 Freshness scoring
Features, all in 0..1 except the prior:
Tier
Meaning
Weight
1
First party or official: vendor docs, pricing and
changelog pages, official repositories and release
pages, government and standards bodies
1.0
2
Package registries and established news or
industry publications
0.7
3
Community: forums, Q and A sites, personal blogs
0.4
4
Unknown or low quality (default)
0.2
support and contra: strength of the best supporting and best contradicting evidence
from the judge labels.
recency: 2^(-age_of_newest_support / half_life). Undated support counts as 0.5. No
support counts as 0.
authority: maximum tier weight among supporting evidence.
agreement: min(1, distinct supporting domains / 2).
coverage: fraction of queries that returned at least one relevant item.
prior: ln((1 - P_stale) / P_stale).
z = b + wV[verdict] + 1.5*support + 0.8*recency + 1.0*authority
      + 0.8*agreement + 0.4*coverage - 2.0*contra + 0.4*prior
b = -1.0
wV: confirmed +2.5, outdated -2.0, contradicted -2.5, unverifiable -0.5
raw_freshness = 100 * sigmoid(z)
These weights are starting points. Sanity check: a confirmed claim with strong, recent,
tier-1, two-domain support scores about 99. An outdated claim with strong contradiction
and a high prior scores under 1.
Calibration: after an Eval Lab run, fit Platt scaling on z against the label (current = 1, stale =
0) on a 70 percent split and test on 30 percent. Use isotonic regression when there are at
least 200 items. Optionally refit the feature weights by logistic regression. Report ECE
before and after. Store the snapshot (method, weights, bins). The active snapshot is
applied at runtime.
evidence_confidence = clamp(judge_confidence x (0.5 + 0.5 x authority of the deciding
evidence) x (0.7 + 0.3 x agreement), 0, 1). Freshness and evidence confidence are
separate numbers: one says whether the claim is current, the other says how sure we are
of that finding.
4.5.10 Entry state machine
unverified --verified--> fresh --time passes--> due --revalidate: confirmed--
> fresh
                           |                     |
                           |                     +--revalidate: outdated--> 
stale --evict_regen--> new entry (fresh)
                           +--cascade: fact outdated--> stale
stale --evict--> evicted
4.5.11 Adaptive intervals
confirmed: interval = min(max_interval, interval x 1.6).
outdated or contradicted: interval = max(min_interval, interval x 0.5) on the fact,
because it has just proven volatile.
unverifiable: retry after max(min_interval, interval / 4).
4.5.12 Singleflight and ledger
verify_fact(fact, force, deadline):
  led = redis.hgetall(cg:fact:{h})
  if not force and led.fresh_until > now(): return LEDGER_HIT(led)
  token = uuid()
  if redis.set(cg:sf:{h}, token, nx=True, px=30000):
      try:
          res = pipeline(fact)                  # triage, tavily, judge, 
score
          write_ledger(res)
          redis.publish(cg:sfdone:{h}, res.id)
          return res
      finally:
          release_if_token(cg:sf:{h}, token)    # compare-and-delete script
  else:
      res = wait_on(cg:sfdone:{h}, timeout=min(deadline, 3s))
      return res or PENDING
4.5.13 Cascade invalidation
on_ledger_write(fact, verdict):
  if verdict in (outdated, contradicted) and two_key_rule(fact):
      for cache_id in redis.smembers(cg:idx:fact:{h}:entries):
          manifest_cas_update(cache_id, status=stale, stale_claims+=fact)
          publish(entry.status_changed)
          if entry.hits_24h >= hot_threshold: enqueue(refresh_ahead, 
cache_id)
4.5.14 Regeneration and priming plans
In every plan the old entry is evicted first and the new entry records
supersedes_entry_id.
4.5.15 Two-key evidence rule
Act on an outdated or contradicted verdict (evict, cascade, regenerate) only when one of
these holds:
1. At least one contradicting evidence item is tier 1.
2. At least two contradicting items come from distinct tier 1 or 2 domains.
3. Judge confidence is at least 0.9 and the corrected value appears verbatim in a tier 1 or
2 source.
Otherwise set the effective verdict to unverifiable with reason evict_rule_unmet and
queue one deep verification (advanced depth plus Extract). Under strict policy,
on_unverifiable applies in the meantime. Under lenient policy, only an annotation is added.
Plan
How it works
Needs
When
A loopback
grounding
Evict, loopback request with
x-cg-ground-id, cg-back
injects evidence, cache
stores the answer under the
original key
V1 to V4,
V9
Preferred
A2 prime by
short-circuit
Verifier generates the
grounded answer with no-
store and returns it to the
user at once. Then a
background loopback
request makes cg-back
short-circuit the provider
call with that stored answer,
so the cache plugin stores it
under the original key
V6 in
addition
Best latency: the user
never waits for the cache
write
B direct
Evict, generate with no-
store, return, rely on
evidence pins injected by
cg-back on later misses
Nothing
special
Fallback if spike S4 fails
This blocks cache poisoning through a single low-quality page.
4.6 Internal API contracts (plugin to Verifier)
All calls carry the header x-cg-internal-key. Wire format is JSON, shown as YAML.
POST /internal/v1/ingest            -> 202 {response_id}
  request_id: string
  cache_id: string | null
  origin: provider | legacy_cache | regenerated
  model_id: string
  provider: string
  messages: [{role, content}]       # last 6, trimmed to 4,000 chars
  response_text: string
  usage: {input_tokens, output_tokens}
  prompt_class: string
  policy: string
  now: timestamp                    # clock time
POST /internal/v1/verify-inline     -> 200
  (same body) + deadline_ms: int
  response: {response_id, status: complete | partial, annotation, 
repaired_text | null}
POST /internal/v1/revalidate        -> 200
  request: {cache_id, policy, deadline_ms, reason: due | stale | unverified, 
force: bool}
  response: {status: complete | partial | failed,
             decision: serve | evict_regen | unverifiable,
             annotation, pending_fact_ids: [id],
             replacement: {text, usage, new_cache_id} | null}
GET  /internal/v1/health            -> 200 {ok, redis, postgres, 
tavily_circuit, queue_depth}
Errors: 401 bad key, 408 deadline exceeded (partial result in body), 429 budget exhausted,
5xx failure. The plugin treats any non-2xx as unavailable and applies the policy.
4.7 Concurrency and consistency
Idempotency: ingest by request id (Redis SET NX, 1 h). Verification by fact lock.
Manifest writes carry a revision number and use compare-and-set so SWR and
cascade updates cannot overwrite each other.
Manifest before entry: the manifest is keyed by Bifrost request id and resolved when
the first hit arrives [verify].
Eviction versus a concurrent hit: serving an entry that was evicted a moment ago is
acceptable and idempotent.
Async cache writes: the cache writes entries asynchronously, so an identical request
immediately after a miss can miss again. Accepted.
Postgres writes: upserts everywhere.
Clock: every comparison uses the clock helper.
Redis and Postgres drift: Postgres is the truth. A reconcile job every 5 minutes
rebuilds missing Redis manifests and drops orphans.
4.8 Performance budgets and capacity
Capacity target: 300 requests per second through the gateway on a laptop-class
machine. The Verifier handles ingest at up to 30 responses per second. Extractor LLM
calls dominate, so ingest.sample_rate is configurable and low-priority ingestion is dropped
when the queue passes 80 percent. Tavily concurrency is 8 and the default budget is 300
credits per hour.
Path
Budget (p99 unless
noted)
Notes
HTTP pre-hook (classify, headers)
0.5 ms
CPU only
cg-front PreLLMHook
0.1 ms
cg-front PostLLMHook on miss
(async)
1 ms
Enqueue only
cg-front PostLLMHook on hit
3 ms
One Redis read plus
decision
Ingest to verdict (async)
p50 6 s, p95 15 s
Depends on Tavily and the
judge
Strict miss, blocking
4.5 s budget
Up to 6 claims in parallel
Blocking revalidation
3 s budget
Ledger hits under 100 ms
Regeneration
12 s budget
Provider latency
Console API reads
200 ms (p95)
Indexed queries
4.9 Reliability mechanisms
4.10 Security and privacy
Dependency
Timeout
Retries
Circuit breaker
Redis (from plugin)
20 ms
0
Opens after 5 failures in 10 s,
half-open after 5 s
Verifier ingest
800 ms
1
Same
Verifier blocking
calls
Policy
budget
0
Same
Tavily
8 s
2 with jittered backoff
(300 ms to 2 s)
Opens after 5 failures in 30 s
Extractor and
judge LLM
20 s
1
Per model
Postgres
2 s
3
Events buffered in a Redis
stream
Threat
Control
Secret leakage
Keys only through environment or secret files.
A log filter redacts them. The console never
receives provider or Tavily keys. .env is git-
ignored
Unauthorized internal API use
x-cg-internal-key (32 random bytes) on every
internal call, constant-time compare. Internal
routes reachable only on the Docker network
Console access
Single admin password (hashed) gives a short-
lived JWT in an httpOnly cookie. CORS locked
to the console origin. CSRF token on state-
changing routes. Login rate limit
Prompt injection through web evidence
F-28: strip markup, delimit, schema-
constrained outputs, whitelisted fields into
regeneration. The two-key rule stops a single
poisoned page from evicting entries
4.11 Observability
Prometheus metrics
Threat
Control
Prompt injection through answers or
prompts
Extractor and judge treat text as data with the
same delimiting and schema validation. They
have no tools. Outputs are never executed
SSRF
The Verifier never fetches URLs itself. Only
Tavily Extract fetches, and only URLs that
Tavily search returned or tier-1 domains from
the registry. No user-supplied URLs
PII reaching third parties
Queries come from entity and attribute
templates, not raw prompts. Regex redaction.
Personal claims skipped. store_content toggle.
A retention job (7 days by default) deletes
requests, responses, claim text and evidence
snippets past retention. Evaluation datasets
are excluded
Cache poisoning and cross-tenant
leakage
Respect Bifrost cache key namespaces.
Manifests are keyed by cache id. Policy rules
can match by virtual key
Denial of wallet
Budgets per response and per hour, playground
rate caps, ingest sampling, circuit breakers
Supply chain
Pinned dependencies and lockfiles. Container
images pinned by version or digest
Data in transit
Plain HTTP inside Compose. TLS terminated at
a reverse proxy for any public demo. Tavily and
providers over HTTPS
Metric
Type
Labels
cg_hook_duration_seconds
histogram
hook
cg_decisions_total
counter
decision, class, policy
Logs: JSON lines with request_id, cache_id, claim_id and fact_key. Decision trace: stored
per request in requests.decision_detail as steps [{name, t_ms, detail}] plus reason codes:
CLAIM_DUE, CLAIM_STALE, MANIFEST_MISSING, LEDGER_HIT, COALESCED,
BUDGET_EXHAUSTED, TWO_KEY_UNMET, PINNED, POLICY_STRICT, FAIL_OPEN,
FAIL_CLOSED. Traces (P2): OpenTelemetry in Go and Python. Dashboards: the console
pages, with an optional Grafana bundle.
Metric
Type
Labels
cg_stale_served_total
counter
policy (stays near zero under
strict)
cg_ingest_queue_depth
gauge
none
cg_ingest_dropped_total
counter
reason
cg_plugin_panics_total
counter
hook
cg_claims_extracted_total
counter
class, claim_type
cg_verifications_total
counter
verdict, trigger, status
cg_ledger_hits_total and
cg_singleflight_coalesced_total
counter
class
cg_tavily_calls_total
counter
endpoint, depth, outcome
cg_tavily_credits_total
counter
class
cg_judge_tokens_total
counter
model, direction
cg_budget_remaining
gauge
kind
cg_cache_evictions_total
counter
reason
cg_regenerations_total
counter
plan, status
cg_verification_seconds
histogram
class, trigger
cg_freshness_score
histogram
class
4.12 Testing strategy
Scripted mock Tavily (world script): a YAML timeline that defines each fact and its value
over simulated time. The mock returns evidence matching the current clock. It powers the
simulated-world workload and the integration tests, and it is always labeled a simulation in
results.
Level
Scope
Tools
Gate
Unit (Go)
Decision engine (table-driven),
classifier, manifest codec, header
logic
go test -race
Green on main
Unit
(Python)
Normalization, scoring, triage,
interval math, evidence
normalization
pytest
Green on main
Contract
Tavily mocked with respx and
recorded fixtures (real responses
saved under tests/fixtures/tavily).
Judge and extractor mocked with
golden outputs. Plugin to Verifier
validated against the schemas in
4.6
pytest, schema
validation
Green before
merge
Integration
Compose test profile: real Bifrost
build, Redis, Postgres, Weaviate,
Verifier with the scripted mock
Tavily and a deterministic fake LLM
server (canned JSON keyed by
prompt hash)
pytest plus
Compose
Green before the
demo build
Live smoke
10 prompts against real Tavily and
real models, run by hand
Playground
Before every
rehearsal
Overhead
300 RPS of cache-hit traffic,
plugins off versus on, p50, p95 and
p99 deltas
k6 or vegeta
Recorded in the
README
UI smoke
(P2)
Playground flow with a mocked
backend
Playwright
Optional
Evaluation
Quick 20-item Eval Lab run
Eval Lab
Before release
4.13 Deployment and environments
Environment variables: TAVILY_API_KEY, provider keys as Bifrost expects them,
CG_INTERNAL_KEY, CG_ADMIN_PASSWORD_HASH, CG_JWT_SECRET,
DATABASE_URL, REDIS_URL, BIFROST_URL, CG_CONFIG_FILE.
Environments: dev (Compose on a laptop), demo (same Compose on one machine,
optional public tunnel), eval (Compose with replay mode). Commands: make up, make
seed, make demo-reset (clears cache, manifests and ledger, resets the clock), make
bench.
4.14 Configuration reference (chronoguard.yaml)
enabled: true
default_policy: standard
redis_url: redis://redis:6379/0
verifier_url: http://verifier:8088
clock: {mode: real, allow_header: false}
classifier:
  time_cues: [latest, current, today, now, newest, as of]
  attribute_cues: [price, pricing, version, release, ceo, founder, law, tax, 
deadline, deprecated]
Service
Image
Port
Depends on
Notes
bifrost
Built from the
fork
8080
redis, weaviate
config.json mounted,
plugins compiled in
weaviate
Pinned version
internal
none
Vector store for the
semantic cache
redis
redis:7
internal
none
AOF on
postgres
postgres:16
internal
none
Volume
verifier
Build ./verifier
8088
redis,
postgres,
bifrost
Internal and public API
console
Build ./console
(static)
3000
verifier
prometheus,
grafana
Optional
9090,
3001
verifier, bifrost
Scrape metrics
  news_cues: [announced, launched, recently, this week]
  realtime_cues: [stock price, exchange rate, weather, live score]
cache:
  hard_ttl_multiplier: 8
  hard_ttl_min: 1h
  hard_ttl_max: 30d
  hot_threshold_hits_24h: 5
ingest: {queue_size: 2000, workers: 4, timeout_ms: 800, sample_rate: 1.0}
budgets: {tavily_credits_per_hour: 300, per_response_credits: 6, 
llm_tokens_per_hour: 400000}
tavily:
  api_key_env: TAVILY_API_KEY
  timeout_ms: 8000
  concurrency: 8
  credits: {basic: 1, advanced: 2, extract_per_5: 1}
models:
  extractor: PROVIDER/CHEAP_MODEL
  judge_primary: PROVIDER/CHEAP_MODEL
  judge_escalation: PROVIDER/STRONG_MODEL
  escalate_below_confidence: 0.6
privacy: {store_content: true, redact_pii_in_queries: true, retention_days: 
7}
Class and policy tables are seeded into Postgres (Document 6, section 6.4) and editable
at runtime. The YAML file only bootstraps them.
4.15 Technical risks, verification items and spikes
Every item below comes from public documentation and must be proven in the Day-0
spikes (Document 5, section 5.5) against the exact Bifrost version you pin.
ID
Assumption to verify
Used by
Fallback if false
V1
Cache-hit metadata (hit type,
cache id) is visible in cg-front
PostLLMHook
F-12
Look up the cache id in Redis by
prompt hash and cache key
V2
Cache entry id equals the Bifrost
request id used by clear-by-
request-id
F-14
Store the mapping from hit
metadata. Clear by cache key
Top technical risks: (1) cache integration assumptions V1 to V6, (2) Tavily latency inside
the blocking budget, (3) judge accuracy and false evictions, (4) streaming limits, (5) time.
Mitigations are in the PRD risk table and Document 5.
ID
Assumption to verify
Used by
Fallback if false
V3
Admin endpoints or plugin
methods exist to clear by request
id and by cache key
F-14
Bump a generation suffix in x-bf-
cache-key for the affected
namespace (coarse invalidation)
V4
x-bf-cache-ttl is accepted per
request and read at write time
F-02
Set one long global TTL and rely
on manifest best_before alone
V5
Cache writes become visible to
lookups within a known delay
F-03, tests
Accept the double miss. Tests
wait
V6
The cache stores a response
produced by a later plugin's
short-circuit
Plan A2
Use Plan A
V7
Supported vector stores and
required configuration for the
semantic cache
Deployment
Use the supported store through
Compose
V8
Plugin ordering semantics (array
order or placement and order
fields)
4.4.1
Adjust config. Last resort: merge
front and back into one plugin
before the cache and use Plan B
V9
Context values propagate from
HTTP hooks to LLM hooks
4.4.2
Keep a Redis state record keyed
by request id
V10
PostLLMHook can attach custom
keys to extra fields, and stream
completion is visible to
PostLLMHook
F-16, F-17
Headers plus the annotation URL
only
V11
Plugin metrics can be exposed
through Bifrost's metrics
endpoint
F-27
Relay by heartbeat to the
Verifier
