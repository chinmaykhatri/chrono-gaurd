# Document 2: Website and System Working Flow
2.1 Purpose and audience
This document describes how ChronoGuard behaves from the moment a request reaches
Bifrost to the moment an operator reads the result in the console. It is the reference for UI
work, QA scripts and demo rehearsal. Component names: cg-front and cg-back (the two
Bifrost plugins), Verifier (FastAPI service), Console (React web app).
Term
Meaning
Priming
Writing the regenerated answer into the cache
under the original key
Simulated clock
A labeled time offset that ages ChronoGuard state
for demos and tests
2.2 System context
  Application (OpenAI SDK, base_url -> Bifrost)                   Browser 
(Console)
          |                                                              |
          v                                                              v
+----------------------------- Bifrost gateway --------------------+   +-----
-------------------+
| HTTP pre-hook (cg-front)                                         |   |  
ChronoGuard Console   |
|  -> cg-front PreLLMHook -> semantic_cache -> cg-back PreLLMHook  |   |  
React, REST, SSE      |
|  -> provider call ->                                             |   +-----
------+------------+
|  cg-back PostLLMHook -> semantic_cache store -> cg-front Post    |            
|
+-------+---------------------+-----------------+------------------+            
v
        |                     |                 |                       +----
--------------------+
    Weaviate                Redis <-------------+---------------------->|  
Verifier (FastAPI)    |
  (semantic cache)   (manifests, ledger,                                |  
workers, scheduler    |
                      locks, queue, clock)                              +----
-+-------------+----+
                                                                              
|             |
                                                                        
Tavily API       Postgres
                                                                     (search, 
extract)  (records)
2.3 Request lifecycles
Hook order is registration order on the way in and the reverse on the way out: cg-front,
semantic_cache, cg-back in; cg-back, semantic_cache, cg-front out. On a cache hit the
provider call is skipped, cg-back never runs, and the post-hooks of cg-front and
semantic_cache still run.
Flow A. Cache miss, async policy (standard or lenient)
1. The app sends POST /v1/chat/completions to Bifrost with x-bf-cache-key (already used
for caching) and optionally x-cg-policy.
2. The cg-front HTTP pre-hook parses the body and runs the prompt classifier (patterns
only, no network), resolves the policy, sets x-bf-cache-ttl to the hard TTL for the
prompt class, strips x-bf-cache-key when the class is realtime, and stamps request
state (request id, policy, prompt class, start time).
3. cg-front PreLLMHook exits early when x-cg-mode is off or x-cg-internal is 1.
4. semantic_cache PreLLMHook checks the key and the embedding. Result: miss.
5. cg-back PreLLMHook does nothing unless x-cg-ground-id is present (Flow H).
6. Bifrost calls the provider.
7. On the way out: cg-back PostLLMHook tags the origin, semantic_cache PostLLMHook
stores the entry (asynchronously), cg-front PostLLMHook runs.
8. cg-front PostLLMHook puts an ingest message on a bounded in-process queue and
returns at once. Headers: x-cg-response-id, x-cg-decision: passthrough, x-cg-cache:
miss.
9. A plugin worker posts the ingest message to the Verifier. The Verifier extracts claims,
classifies them, builds fact keys, consults the ledger, triages, verifies through Tavily
and the judge, scores, persists, writes the manifest to Redis and publishes SSE events.
10. The client or console reads annotations from GET /api/v1/responses/{id}/annotations
or over SSE.
State change: a new cache entry (unverified) gets a manifest (fresh or due) 3 to 8 seconds
later. Latency added for the user: under 1 ms (enqueue only).
Flow A2. Cache miss, strict policy (verify before return)
Steps 1 to 7 as in Flow A, then:
8. cg-front PostLLMHook calls POST /internal/v1/verify-inline on the Verifier with a
deadline of blocking_budget_ms (default 4500).
9. The Verifier runs the same pipeline with claims verified in parallel (at most 6 claims,
ordered by triage priority).
10. If every claim finishes in time, annotations are attached to the response
(extra_fields.chronoguard [verify], plus headers). If a claim is outdated and
regen_on_stale is true, repair mode regenerates the answer with evidence (extra time
bounded by regen_budget_ms).
11. If the deadline passes, finished claims are annotated and unfinished claims show
status pending. on_unverifiable then decides: serve_annotated (fail open) or
fail_closed (error code chronoguard_unverifiable, HTTP 503, no provider fallbacks).
Flow B. Cache hit, every claim fresh
1. Steps 1 to 3 as in Flow A.
2. semantic_cache PreLLMHook returns a short-circuit response. The provider is
skipped.
3. semantic_cache PostLLMHook adds cache-hit metadata (hit type, cache id) [verify
field names].
4. cg-front PostLLMHook reads that metadata, loads the manifest from Redis (one round
trip), and evaluates each claim against now() (simulated-clock aware).
5. Decision: serve. Headers: x-cg-decision: serve, x-cg-freshness: lowest claim score, x-
cg-cache: hit. Annotation is built from the manifest.
6. Fire-and-forget counter increment for popularity (hits_24h).
State change: counters only. Latency added: <= 3 ms p99. Tavily calls: zero.
Flow C. Cache hit, claim due, standard or lenient (serve-while-revalidate)
1. Steps 1 to 4 as in Flow B. At least one claim has next_check_at <= now().
2. Decision: serve_swr. The cached answer is served now with annotation status due.
3. A revalidation job is enqueued per due fact (deduplicated by fact key, coalesced by
singleflight).
4. The Verifier verifies. The ledger and manifest are updated. An outdated verdict starts
Flow E.
5. The next request sees the updated state.
Effect: the user pays nothing. The staleness window equals the verification latency
(seconds).
Flow D. Cache hit, claim due or known stale, strict policy
1. Steps 1 to 4 as in Flow B.
2. Branch D1, claim due: cg-front calls POST /internal/v1/revalidate with
revalidate_budget_ms (default 3000). Ledger hits return in milliseconds. Confirmed:
serve, and extend next_check_at by the adaptive interval. Outdated: go to D2.
Unverifiable or timeout: apply on_unverifiable.
3. Branch D2, claim known stale (for example from a cascade): evict the entry (Bifrost
cache clear by id), build a grounding bundle, regenerate (Flow H), replace the response
body, and return x-cg-decision: evict_regen with an annotation listing corrected claims
and sources.
State change: old entry evicted, new entry created under the original key with a new
manifest.
Flow E. Cascade invalidation
1. A verification returns outdated or contradicted for a fact and passes the two-key
evidence rule.
2. The Verifier updates the Fact Ledger (current value set to the corrected value, interval
shortened) and creates an evidence pin.
3. It reads the Redis set of entries that mention the fact and marks each manifest stale,
listing the stale claim ids.
4. Entries with hits_24h at or above the hot threshold are queued for refresh-ahead
regeneration. Others wait for their next hit (lazy).
5. An entry.status_changed event is published per entry. Cache Explorer updates live.
State change: N entries move to stale within 2 seconds of the verdict.
Flow F. Failure paths
Failure
Detection
Behavior
Tavily 429, 5xx or
timeout
Client error
Retry with backoff (max 2). Circuit opens
after 5 failures in 30 s. Claims become
unverifiable and the policy decides
Judge returns invalid
JSON
Schema
validation
One retry, then escalate model, then
unverifiable
Budget exhausted
Token bucket
empty
Degrade: basic depth, then fewer claims,
then skip. Event budget_exhausted
Redis down
Plugin lookup
error
Plugin passes the request through (fail open)
and logs. Strict classes with fail_closed
return chronoguard_unverifiable
Flow G. Streaming
Pass-through (P1): the stream chunk hook only records the response id. Ingestion
happens when the stream completes, with the accumulated text [verify how Bifrost
presents stream completion to PostLLMHook]. Annotations arrive through the URL
and SSE.
Cache hits on streaming requests: the cached response is replayed as a stream
[verify]. The same decision flow runs from the manifest. Headers are set in the HTTP
post-hook.
Buffer-and-release (P2, strict only): the chunk hook holds chunks, verification runs at
stream end, then one merged chunk is released. The time to first token is lost, so this
stays opt-in.
Flow H. Evidence-grounded regeneration (Plan A, loopback)
1. The Verifier stores a grounding bundle in Redis (evidence plus corrected facts) for 10
minutes.
2. It issues a loopback request to Bifrost with the original messages and headers x-cg-
internal: 1, x-cg-ground-id: {id}, x-bf-cache-key: {original key}, x-bf-cache-ttl: {hard
TTL}.
3. cg-front sees x-cg-internal and skips decision logic. The cache misses because the old
entry was evicted.
4. cg-back PreLLMHook loads the bundle and appends a system message: use the
supplied evidence for the listed facts, cite sources, do not repeat outdated values.
Failure
Detection
Behavior
Verifier down
Health check fails
Ingest queue drops with a counter. Hits use
manifests already in Redis. Blocking calls fail
per policy
Postgres down
Write errors
Verifier buffers events in a Redis stream and
retries. Plugins unaffected
Plugin panic
recover()
Request continues unmodified. Metric
cg_plugin_panics_total
Loopback recursion
x-cg-internal
header
Internal calls skip decision logic
5. The provider answers. semantic_cache PostLLMHook stores the answer under the
original key, because that key was computed before cg-back changed the messages
[verify in S4].
6. The answer returns to the Verifier, which hands it to the waiting outer request (Flow D)
and ingests it as a new response with origin regenerated. Its claims inherit verified
status from the ledger.
Plan B (fallback if S4 fails): evict, generate with no-store through the Verifier, return the
answer, and rely on evidence pins that cg-back injects on later misses.
Flow I. Simulated clock (demo and evaluation)
1. The console sets a clock offset (for example +3 days) or freezes the clock. State lives in
Redis key cg:clock.
2. Plugins and Verifier read time only through the clock helper. Timestamps that drive
behavior (best_before, next_check_at, fresh_until) use clock time. Audit timestamps
use real time.
3. Responses and the console show a Simulated badge whenever the offset is not zero.
4. Tavily and the web are real, so the clock ages only our own state and cannot change the
world. Experiments that need the world to change use the scripted mock Tavily (TRD
4.12).
Flow J. Evaluation run
1. The user picks a dataset and variants in Eval Lab.
2. The runner executes each variant over every item with concurrency limits.
ChronoGuard variants call the Verifier pipeline directly. Baselines run their own logic.
3. Per item it stores predicted verdict, freshness, credits, tokens and latency in
eval_run_items.
4. Metrics (precision, recall, F1, AUROC, ECE, Brier, abstain rate, cost, latency) are stored
in eval_runs.metrics. Progress streams as eval.progress events.
5. Calibration can be fitted on one split and applied to another. Snapshots are stored.
6. The report page renders the PR curve, calibration plot, accuracy-versus-cost chart and
ablation table, with JSON and CSV export.
2.4 Console information architecture
Global header (every page): environment badge (Bifrost URL and health), clock chip
(Real, or Simulated +3d 04:00, with a popover to set, freeze, advance and reset), budget
meters (Tavily credits this hour, LLM tokens this hour), SSE connection dot, user menu.
Global rules: status colors are Fresh green, Due amber, Stale red, Unverified gray, Skipped
outline. Times show clock time with a tooltip for real time. Every table is filterable and
exportable as CSV. Every page has loading, empty and error states.
2.5 Page specifications
Overview (/)
Purpose: answer in 10 seconds whether it is working and whether it pays off.
Route
Page
Purpose
/login
Login
Single admin password for the MVP
/
Overview
KPIs and a live ticker
/playground
Playground
Ask questions, see claims and decisions
/feed
Live Feed
Stream of requests and decisions
/cache
Cache Explorer
Inventory with status countdowns and
actions
/cache/:id
Entry detail
Manifest, claims, history
/claims/:id
Claim Inspector
Evidence and score breakdown
/facts and /facts/:id
Fact Ledger
Facts, verdicts, cascade impact
/policies
Policies
Policies, rules, class settings
/costs
Costs and
Latency
Spend, savings, latency
/eval and
/eval/runs/:id
Evaluation Lab
Datasets, runs, reports
/settings
Settings
Connections, key status, model cutoffs, clock
Layout: six KPI cards (Stale answers prevented, Cache hit rate, Tokens saved, Tavily
credits spent, Net savings, Hook overhead p99). Middle row: decisions over time
(stacked by decision) and entry status donut. Bottom: live ticker of the last 20 events.
Data: GET /api/v1/summary?window=24h plus SSE.
Interactions: window selector (1h, 24h, 7d). Clicking a KPI opens Costs or Feed with
the matching filter.
Empty state: a connect checklist (Bifrost reachable, plugins loaded, Tavily key present,
first request sent).
Playground (/playground)
Purpose: the demo stage and a developer sandbox.
Layout: chat on the left. Above the input: model selector (from Bifrost), policy selector,
cache toggle (sends x-bf-cache-key), clock chip. Right panel tabs: Decision trace,
Claims, Evidence, Raw.
Send flow: the console calls POST /api/v1/playground/chat. The server adds the
headers, calls Bifrost and returns the response, response id and trace id.
Rendering: claims are underlined by status color. Hover shows the freshness score.
Under the strict policy a progress strip shows Extracting claims, Searching, Judging,
Scoring, with a spinner per claim.
Claim click: opens the claim in the right panel with evidence cards, corrected value
and source links, plus a button to open the Claim Inspector.
Regeneration: when an answer was repaired or regenerated, a diff view shows the old
text struck through and the new text.
Errors: chronoguard_unverifiable shows the reason and which claims could not be
verified.
Live Feed (/feed)
Purpose: operational view of every request.
Layout: table with time, model, prompt preview, cache status, decision badge, lowest
freshness, claim count, verification latency and cost. Filters: decision, class, policy,
cache status. Pause button. Row expand shows the decision trace.
Data: GET /api/v1/requests with a cursor, plus SSE request.completed and
decision.made.
Cache Explorer (/cache and /cache/:id)
Purpose: see and control cache health.
Layout: table with prompt preview, model, status badge, best_before countdown, last
verified, hits in 24 hours, claim count and class chips. Filters: status, class, model, hot
only. Bulk select.
Actions: Revalidate now, Evict, Pin (exempt from eviction for demos), Open detail.
Bulk: revalidate or evict selected.
Entry detail: manifest viewer, claim list with statuses, history timeline (created,
verified, due, evicted, regenerated), linked requests, link to the entry it supersedes.
Behavior: the countdown turns amber in the last 10 percent of its life and red when
due. Rows flash on live status change.
Claim Inspector (/claims/:id)
Purpose: explain a verdict.
Layout: header with claim text, entity, attribute, class, status badge and freshness
gauge. Sections: Score breakdown (bars per feature contribution), Evidence (cards
with title, domain, authority tier, publish date, snippet with the match highlighted, label
supports or contradicts), Judge (verdict, corrected value, confidence, rationale),
Timeline (verifications), Where used (entries and responses).
Actions: Re-verify now (bypasses the ledger), Mark reviewed.
Fact Ledger (/facts) - P1
Table of facts: fact key, class, current value, last verdict, fresh until, interval, entries
affected. Detail page shows history and the cascade list. Action: Re-verify.
Policies (/policies) - P1 (YAML file is the P0 fallback)
Policy list with an editor form (strictness, mode, budgets, thresholds, on_unverifiable,
regeneration flag). Class table (half-life, soft TTL, intervals, strictness, Tavily profile).
Rules table (match by virtual key, model, header, path, with priority). Saving triggers a
hot reload. A dry-run box resolves a pasted prompt to its class and policy.
Costs and Latency (/costs)
Cards: Saved by cache hits, Spent on Tavily, Spent on extraction and judging, Spent on
regeneration, Net. Charts: spend by day and kind, savings waterfall, spend by class,
latency histograms (hook overhead on hits, verification, regeneration). Table of the
most expensive facts. CSV export.
Evaluation Lab (/eval and /eval/runs/:id)
Datasets list (name, version, item count, label date) with import and export. Run
builder: dataset, variants (B0 to B3, CG full, ablations), model and Tavily settings,
concurrency, Start. Runs table with status and headline metrics.
Run report: metric cards, PR curve, calibration plot, accuracy-versus-cost scatter, per-
class table, confusion matrix, ablation table, and a failure browser (click a wrong item
to see its evidence).
Settings (/settings)
Connection checks (Bifrost, Verifier, Redis, Postgres, Tavily key present, model
access). Model cutoff table editor. Clock controls. Privacy (store content, retention).
Danger zone (flush manifests, reset demo data).
2.6 User journeys
UJ-1 Operator onboarding: Settings (all checks green) -> Policies (choose default) ->
Playground sample prompt -> see the first scored claim. Target: 10 minutes.
UJ-2 Investigate a stale answer: Feed shows an evict_regen row -> expand the trace -
> open Claim Inspector -> read evidence -> open the Cache Explorer entry -> follow
the supersedes link.
UJ-3 Tune policy: Costs shows high Tavily spend on news_events -> Policies -> raise
that class interval or set it to standard -> Save -> watch spend drop.
UJ-4 Run evaluation: Eval -> pick dataset -> choose variants -> Start -> watch progress
-> open the report -> export.
UJ-5 Judge demo path: see 2.8.
2.7 Real-time events (SSE)
Event type
Key payload fields
Used by
request.completed
request_id, model, cache_status, decision,
min_freshness, latency
Feed, Overview
decision.made
request_id, decision, reason codes, claim
states
Feed, Playground
trace
2.8 Demo script (3 minutes)
Pre-flight (10 minutes before): stack healthy on Settings; Tavily key present; clock real;
cache cleared; rehearsed prompts re-tested within 24 hours; backup video ready; budget
meters full; two browser tabs open.
Prompt selection rule: pick questions whose true answer changed after the demo
model's knowledge cutoff (a software version, a vendor price, a leadership change). Keep
six candidates and verify each the day before.
Event type
Key payload fields
Used by
claims.extracted
response_id, claim_count, classes
Playground
verification.started
verification_id, fact_key, trigger
Playground
progress
verification.finished
verification_id, fact_key, verdict, freshness,
credits, latency
Playground, Costs
fact.updated
fact_id, last_verdict, current_value,
fresh_until
Fact Ledger
entry.status_changed
cache_entry_id, from, to, cause
Cache Explorer
entry.evicted
cache_entry_id, reason
Cache Explorer
regen.finished
regeneration_id, status, plan, latency
Playground, Feed
budget.updated
window, credits_used, credits_cap,
tokens_used
Header meters
budget.exhausted
window, kind
Header, Overview
clock.changed
mode, offset_seconds
Header chip
eval.progress
run_id, done, total
Eval Lab
Time
Action
What the judge sees
Say
0:00
Open Overview
Live counters at zero
Models state outdated
facts and caches repeat
them
Fallbacks: if Tavily is slow, switch to replay mode (stored evidence fixtures) and say so. If
the live prompt turns out to be fresh, use the backup prompt. If the stack fails, play the
video.
