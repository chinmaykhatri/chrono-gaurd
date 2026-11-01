# Document 3: Feature Specifications
3.1 How to read this document
Each feature lists purpose, trigger and inputs, behavior, outputs, configuration, edge
cases and acceptance tests (AT). UI features reference the Document 2 page specs and
add only behavior rules.
Time
Action
What the judge sees
Say
0:20
Playground, strict policy,
cache on, ask the time-
sensitive question
Progress strip, claims
underlined, a stale claim in
red with corrected value
and source
A first answer is verified
per claim. This is Tavily PS
01
1:00
Ask a paraphrase
Instant hit, fresh scores,
zero Tavily calls, overhead
in milliseconds
The cache keeps its
savings
1:20
Set clock to +3 days, ask
the paraphrase again
Entry due, blocking
revalidation, then
confirmed or evict and
regenerate with a diff
The cache decides with
facts, not clocks
1:50
Open Cache Explorer
after a cascade
Several entries flip to stale
at once
One changed fact
invalidates every answer
that mentions it
2:20
Costs, then the Eval Lab
report
Net savings, PR curve,
calibration, overhead table
Numbers, including the
weak ones
2:50
Show repository and pull
request
Plugin code and docs
A mergeable Bifrost
plugin
ID
Feature
Component
Priority
F-01
Request classifier and policy resolver
cg-front
P0
ID
Feature
Component
Priority
F-02
Cache control headers
cg-front
P0
F-03
Ingestion pipeline
cg-front, Verifier
P0
F-04
Claim extraction
Verifier
P0
F-05
Volatility classes and fact keys
Verifier
P0
F-06
Fact Ledger and singleflight
Verifier, Redis
P0
F-07
Triage and budget scheduler
Verifier
P0
F-08
Evidence retrieval (Tavily)
Verifier
P0
F-09
Verdict judge
Verifier
P0
F-10
Freshness scoring and calibration
Verifier
P0
F-11
Claim manifest and best_before
Verifier, Redis
P0
F-12
Cache decision engine
cg-front
P0
F-13
Revalidation: SWR, blocking, refresh-ahead
cg-front, Verifier
P0, P1
F-14
Eviction and cascade invalidation
Verifier
P0
F-15
Grounded regeneration and priming
Verifier, cg-back
P0
F-16
Annotations and repair mode
cg-front, Verifier
P0, P1
F-17
Streaming behavior
cg-front
P1, P2
F-18
Policies and configuration
all
P0
F-19
Simulated clock
all
P0
F-20 to F-25
Console features
Console
P0, P1
F-26
Evaluation Lab
Verifier, Console
P0
F-27
Observability
all
P0
F-28
Safety, privacy and evidence hardening
Verifier
P0
F-29
Code-aware claims
Verifier
P2
3.2 Gateway-side features
F-01 Request classifier and policy resolver (P0; FR-001, FR-036, FR-050)
Purpose: decide in microseconds, with no network call, how time-sensitive the prompt
is and which policy applies.
Trigger and inputs: HTTP pre-hook on every chat completion. Body (messages, model,
stream), headers (x-cg-policy, x-cg-mode, virtual key), config rules.
Behavior: (1) Parse the JSON body once. Take the last user message plus up to two
earlier turns, truncated to 2,000 characters. (2) Match pattern lists per class: time cues
(latest, current, today, now, this year, as of, newest), attribute cues (price, pricing, cost
per, version, release, CEO, founder, law, tax rate, deadline, deprecated), news cues
(announced, launched, recently, this week), realtime cues (stock price, exchange rate,
weather, live score). (3) Prompt class is the highest-volatility class matched, otherwise
slow_facts. (4) Resolve policy: x-cg-policy header, else rule match by virtual key, model
and path in priority order, else the default policy. (5) Stamp request state.
Outputs: prompt_class, policy_id, skip flag.
Config: pattern lists in chronoguard.yaml, rules in policy_rules.
Edge cases: unparsable body or non-chat endpoint: skip ChronoGuard. Unknown
policy name in the header: use default and log.
AT: table-driven test over 100 labeled prompts with at least 90 percent agreement on
time-sensitive versus not. p99 runtime under 0.3 ms.
F-02 Cache control headers (P0; FR-030, FR-036)
Purpose: give the Bifrost cache soft and hard expiry semantics without changing
cache code.
Behavior: in the HTTP pre-hook set x-bf-cache-ttl to hard_ttl(prompt_class) = clamp(8
x soft TTL, 1 hour, 30 days). For the realtime class remove x-bf-cache-key so the
request bypasses the cache, and record decision bypass. Respect a client-supplied x-
bf-cache-ttl unless policy.force_ttl is true. Do nothing when x-cg-mode is off.
Edge cases: a request with no x-bf-cache-key does not use the cache. ChronoGuard
still verifies the answer, and the decision engine returns passthrough. This opt-in
behavior comes from Bifrost.
AT: spy test checks header values per class.
F-03 Ingestion pipeline (P0; FR-002, FR-004)
Purpose: get responses to the Verifier without ever blocking the response.
Behavior: cg-front PostLLMHook (miss, or a legacy hit without a manifest) builds an
ingest message: request id, cache id, origin, model, provider, last 6 messages trimmed
to 4,000 characters, response text, usage, prompt class, policy id, clock time. It goes
onto a bounded channel (size 2,000). A pool of 4 workers posts to the Verifier with an
800 ms timeout and idempotency key = request id. Queue full: drop and count
cg_ingest_dropped_total. Verifier error: one retry after 200 ms, then drop. The Verifier
dedupes with Redis SET NX for 1 hour.
Edge cases: empty text and tool-call-only responses are skipped. Responses over
12,000 characters are cut at a paragraph boundary and flagged truncated. With n > 1
only choice 0 is ingested.
AT: with the Verifier stopped, p99 latency is unchanged versus plugins off. Overflow is
counted.
3.3 Verifier-side features
F-04 Claim extraction (P0; FR-010, FR-013)
Purpose: turn answer text into atomic, verifiable claims.
Behavior: (1) Pre-filter: when the text has no digits, no capitalized entities and no time
cues and the prompt class is not time-sensitive, store zero claims. (2) Split long
answers by paragraph into chunks of at most 1,500 tokens and run up to 3 in parallel. (3)
Call the extractor model through Bifrost with temperature 0 and a JSON schema.
Rules: only checkable statements about the world, one entity and one attribute each,
exact source span, claim_type, importance from 0 to 1 (central to the answer is high),
as_of_hint when the text states a date, flag personal data. (4) Validate with pydantic,
retry once on invalid JSON, cap at 25 claims. (5) Align spans to the text by exact then
fuzzy match (threshold 90), falling back to the sentence. (6) Claims that are not facts
or are personal are stored as skipped with a reason.
Outputs: claims rows with status pending or skipped.
Config: extractor.model, max_claims, chunk size.
Edge cases: code blocks are excluded (F-29 handles them). Non-English answers keep
the claim text in that language but use English fact keys. A refusal yields zero claims
and a metric.
AT: gold set of 20 answers: recall of time-sensitive claims at least 0.8, span alignment
success at least 95 percent.
F-05 Volatility classes and fact keys (P0; FR-011, FR-012)
Behavior: the extractor proposes a class. The Verifier checks it against an attribute
vocabulary (latest_stable_version maps to software_versions, price_per_month to
pricing_plans, ceo to org_people, and so on). On conflict the vocabulary wins. fact_key
= class:entity_slug:attribute[:qualifier]. entity_slug is lowercase, ASCII-folded, legal
suffixes removed (inc, llc, ltd), punctuation turned into hyphens. The qualifier carries
plan, model, region or edition when present. Aliases resolve through entity_aliases.
The fact is upserted and prior_stale is computed (F-10).
Edge cases: unknown attribute becomes other:{slug} with the extractor's class. A
claim with no entity is skipped with reason no_entity.
AT: 50 paraphrase pairs map to the same fact key at least 85 percent of the time.
F-06 Fact Ledger and singleflight (P0; FR-012, FR-023)
Purpose: one verification per fact per validity window.
Behavior: Redis hash cg:fact:{hash} mirrors the facts table. verify_fact() returns a
ledger hit when fresh_until is in the future and no force flag is set. Otherwise it takes
the lock cg:sf:{hash} with SET NX PX 30000. The leader runs the pipeline. Followers
subscribe to cg:sfdone:{hash} and wait up to min(deadline, 3 s), then return pending.
The lock is released with a token-checked script. Manual re-verify bypasses the ledger.
Edge cases: leader crash: the lock expires in 30 s and the next caller leads. Clock
changes use clock time.
AT: 100 concurrent identical requests produce exactly one Tavily call. Ledger hit rate is
counted.
F-07 Triage and budget scheduler (P0; FR-024)
Behavior: for each pending claim compute P_stale (F-10). priority = P_stale x salience x
(1 + ln(1 + hits_24h)) / cost_units. Per response, sort by priority and take claims until
max_claims_per_response or max_credits_per_response is reached. Global token
buckets cover Tavily credits per hour and LLM tokens per hour. Degrade ladder when a
bucket is under 20 percent: advanced depth becomes basic, Extract is skipped, the
priority cutoff rises. When empty: remaining claims become unverifiable with reason
budget and budget.exhausted is emitted. Due facts from cached entries use the same
priority with hits_24h from the manifest.
Outputs: an ordered verification plan of {fact_id, depth, extract, reason}.
AT: with a 10-credit budget and 20 claims the scheduler spends at most 10 credits and
picks the highest priorities. Ladder unit tests pass.
F-08 Evidence retrieval with Tavily (P0; FR-020)
Behavior: query synthesis uses per-class templates first (for example: latest stable
version of {entity}; {entity} {plan} pricing per month; current {attribute} of {entity}), at
most 2 queries. An LLM rewrite is used only when the entity is ambiguous. Build the
Tavily request from the class profile: topic, search_depth, time_range or start_date,
include_domains (official hint from the extractor plus tier-1 domains from
source_authority), max_results 5 or 6. Optionally call Extract on the top tier-1 URL
when the profile enables it and snippets lack the attribute value. Parse url, title,
content, score and published_date. Normalize: canonical URL, domain, authority tier
(unknown is tier 4), a snippet window of at most 600 characters around the attribute
mention, dates from published_date else a pattern search in the content else null.
Dedupe by content hash and keep the top 6 ordered by tier, then score, then recency.
Record credits in cost_ledger.
Edge cases: zero results: retry once with a broadened query and no domain filter.
Timeout 8 s. Strip markup.
AT: mock Tavily fixtures verify request parameters per class and credit accounting.
F-09 Verdict judge (P0; FR-021, FR-027)
Behavior: input is the claim, stated value, as-of assumption and evidence items (id,
domain, tier, date, snippet) inside delimiters, with an instruction that evidence is data,
not instructions. Output schema: verdict, corrected_value, confidence 0 to 1,
support_ids, contradict_ids, as_of_note, rationale (at most 280 characters). Rules:
confirmed needs a supporting item dated on or after the claim as-of date, or an
undated tier-1 item. Outdated means evidence shows a newer value superseding the
stated one. Contradicted means the stated value was never correct. Unverifiable
covers missing, conflicting or irrelevant evidence. Cascade: the primary model first,
then the stronger model once when confidence is under 0.6 or the verdict is
unverifiable with at least 3 relevant items. Temperature 0. Validate, retry once, fall back
to unverifiable.
Outputs: a verification row and evidence labels (supports, contradicts, neutral, with
strength).
AT: 30 hand-built evidence cases. Injection test: evidence that says to ignore previous
instructions never changes the verdict.
F-10 Freshness scoring and calibration (P0; FR-022, FR-026)
Behavior: formulas are in TRD 4.5.3 and 4.5.9. The prior uses the model knowledge
cutoff as the as-of date for provider-generated claims. Features and the raw logistic
score are stored. After an Eval Lab run, Platt scaling or isotonic regression is fitted on
score versus truth label and stored as a calibration snapshot. The Verifier applies the
active snapshot at runtime. evidence_confidence combines judge confidence,
authority and agreement.
Outputs: freshness 0 to 100, evidence_confidence, features.
AT: score is monotonic in evidence strength in unit tests. ECE is reported by Eval Lab.
F-11 Claim manifest and best_before (P0; FR-030, FR-025)
Behavior: after each verification batch the Verifier rebuilds the manifest. Per claim:
fact key, class, status, freshness, last_verified_at, next_check_at (the fact's
fresh_until). Entry best_before is the minimum next_check_at over non-static claims,
or null when there are none. hard_expiry = created_at + hard TTL. Entry status: stale if
any claim is stale, unverified if any is pending, due if best_before is in the past,
otherwise fresh. The manifest is written to Redis cg:manifest:{cache_id} (TTL
hard_expiry + 1 day) and to cache_entries. Adaptive interval (P1): after confirmed,
interval = min(max, interval x 1.6). After a detected change, interval = max(min, interval
x 0.5). After unverifiable, retry in max(min, interval / 4). The initial interval is the class
soft TTL.
Edge cases: the manifest can be written before the cache entry id is known. It is keyed
by Bifrost request id and resolved on the first hit [verify]. Orphans expire.
AT: unit tests for the status derivation table.
F-12 Cache decision engine (P0; FR-003, FR-031, FR-051)
Purpose: a pure function decide(manifest, policy, now, flags) that returns a decision
plus reason codes.
Rules in order: (1) plugin disabled or internal request: passthrough. (2) Any claim stale:
evict_regen when strict or regen_on_stale, else evict_lazy. (3) Any claim due: strict
gives revalidate_blocking, others serve_swr. (4) Manifest missing or any claim pending:
see the table. (5) Otherwise serve. After a blocking verification: freshness below
evict_below gives evict_regen. Freshness below serve_min_freshness serves with a
low_confidence annotation, or applies on_unverifiable under strict.
AT: table-driven tests cover every cell. Property test: under strict, serve is never
returned when any claim is stale. Runtime under 50 microseconds.
F-13 Revalidation: SWR, blocking, refresh-ahead (P0, P1; FR-031, FR-035)
Purpose: keep cached answers correct without paying for verification on every hit.
SWR: on serve_swr, cg-front asks the Verifier to revalidate the due facts. Requests are
deduplicated per fact with Redis SET NX cg:rv:{hash} for 60 s. The Verifier runs
verify_fact for each due fact, updates the ledger, manifests and Postgres, and starts F-
14 on an outdated verdict.
Blocking: cg-front calls POST /internal/v1/revalidate with cache_id and deadline_ms.
The Verifier verifies only due or pending facts (ledger hits first) and returns decision,
annotations and an optional replacement. On deadline it returns a partial result with
the pending list and cg-front applies on_unverifiable.
Refresh-ahead (P1): every 30 s a scheduler selects entries with hits_24h at or above
hot_threshold (default 5) whose best_before falls inside the lead time (10 percent of
the interval or 5 minutes) and enqueues low-priority revalidation, so hot entries rarely
reach the blocking path.
Edge cases: facts shared by many entries cost one call through the ledger. An
unverifiable result follows the retry rule in F-11.
AT: under standard, a due entry is served in under 3 ms and verified in the background.
Under strict, ledger-hit revalidation finishes inside revalidate_budget_ms. Refresh-
ahead lowers the blocking-path share in the simulated workload.
Manifest state
strict
standard
lenient
No manifest
revalidate_blocking for strict classes, else
fail_open
fail_open
fail_open
Any claim stale
evict_regen
evict_regen
evict_lazy
Any claim due
revalidate_blocking
serve_swr
serve_swr
Any claim
pending
wait, then on_unverifiable
fail_open
fail_open
All fresh
serve
serve
serve
F-14 Eviction and cascade invalidation (P0; FR-032, FR-033)
Eviction: the Verifier (or cg-front) calls the Bifrost cache clear by cache id [verify
admin endpoint, else the plugin method], then marks the entry evicted in Postgres and
Redis with a reason (stale_fact, manual, ttl).
Cascade: when a ledger write records outdated or contradicted and the two-key rule
passes (F-28), read the Redis set cg:idx:fact:{hash}:entries. For each cache id set
manifest status stale with the stale claim ids and publish entry.status_changed. Hot
entries are queued for refresh-ahead regeneration. Others heal lazily on their next hit.
The index is maintained with SADD on manifest write and SREM on eviction.
Edge cases: if the clear call fails the entry stays but its manifest is stale, so every hit
takes the evict_regen path and retries the clear (self-healing). Evicting an entry that is
being served is safe and idempotent. Pinned entries are annotated stale but not
evicted automatically.
AT: after the verdict all N referencing manifests are stale within 2 s. An evicted entry
no longer produces a cache hit [verify in an integration test].
F-15 Grounded regeneration and priming (P0; FR-034)
Purpose: replace a stale answer with a corrected one and make the cache hold the
corrected one.
Behavior (Flow H): the grounding bundle holds corrected facts (fact key, old value,
new value, as-of date), evidence items (url, title, date, snippet) and instructions,
capped at 8 evidence items and 3,000 characters with evidence text escaped. cg-back
PreLLMHook appends a system message saying the time-sensitive facts below were
verified against live sources, to use them, to cite the source for each, and not to repeat
superseded values. After the provider answers, check whether the text still contains
an old value (entity and string match). If so retry once with a stronger instruction,
otherwise return with annotation regen_incomplete. The new response is ingested
with origin regenerated. Claims for already verified facts inherit status with no new
Tavily calls. The new entry records supersedes_entry_id.
Plan B: evict, generate through the Verifier with no-store, return the answer, and inject
evidence pins on later misses through cg-back.
Edge cases: model refusal. Regeneration slower than regen_budget_ms (default 12 s):
return the old answer annotated stale together with a corrected-facts notice built
from the bundle (no LLM) and finish regeneration in the background so the next
request hits the corrected entry.
AT: after regeneration the next paraphrase is a hit that returns the corrected answer.
Cost is recorded as llm_regen.
F-16 Annotations and repair mode (P0, P1; FR-040, FR-041, FR-044)
Annotation object: response_id, decision, cache status, min_freshness, mode (inline,
async or manifest), and claims[] with claim_id, text, span, status, freshness, verdict,
corrected_value, evidence[] (url, title, domain, published_at, tier), checked_at,
next_check_at.
Delivery: headers x-cg-response-id, x-cg-decision, x-cg-freshness (lowest score,
integer), x-cg-cache, x-cg-annotations-url. Body extension extra_fields.chronoguard
[verify] carries the object, truncated to 8 claims, with the full object at the URL. An
async miss returns status pending plus the URL.
Repair mode (strict, first generation): when blocking verification finds outdated
claims and regen_on_stale is true, the answer is regenerated with evidence (F-15)
before it is returned. The original text is kept in the annotation as original_text for the
diff view.
Edge cases: headers carry only integers and short tokens. Clients that ignore
extension fields still work.
AT: schema test. Inline annotation present inside the budget for a 3-claim answer.
Async annotation retrievable in under 10 s.
F-17 Streaming behavior (P1, P2; FR-042, FR-043)
Pass-through (P1): no transformation. Ingestion happens at stream completion. x-cg-
response-id is set in the HTTP post-hook. Annotation arrives through the URL and SSE.
Cache hit on a stream: the decision comes from the manifest and the annotation
travels in headers. Under strict with evict_regen, a stream cannot be retracted, so the
cached text is served with a stale annotation and regeneration runs in the background,
unless buffered mode is on.
Buffer-and-release (P2): policy.stream_buffer=true holds content chunks until the
end, verifies, then releases one merged chunk and the final chunk. Maximum hold is
blocking_budget_ms. On timeout it releases with an annotation.
AT: stream bytes are identical apart from headers in the test. Time to first token grows
by at most 1 ms at p99.
F-18 Policies and configuration (P0; FR-050, FR-051, FR-052)
Behavior: three built-in policies are seeded. Rules resolve by priority. Class overrides
are allowed (for example strict overall but news_events behaves as standard).
chronoguard.yaml bootstraps. Postgres tables hold runtime edits. Redis keys cg:pol:
{id} cache policies and a version counter cg:cfg:version signals change. Plugins poll the
version every 5 s. The Verifier listens on pub/sub. Saves are validated against a schema
and invalid configs are rejected with a message.
AT: change on_unverifiable and see the behavior change within 5 s.
F-19 Simulated clock (P0; FR-067)
Behavior: modes are real, simulated (offset in seconds) and frozen (at a timestamp).
State lives in Redis cg:clock. One now() helper serves the plugin (cached for 1 s in-
process) and the Verifier. API: GET and POST /api/v1/clock (set, advance by delta,
freeze, reset). The x-cg-now header is honored only when clock.allow_header is true,
for the evaluation harness.
Setting
strict
standard
lenient
mode
verify_before_return
async
async
blocking_budget_ms
4500
n/a
n/a
revalidate_budget_ms
3000
n/a
n/a
regen_budget_ms
12000
12000
n/a
serve_min_freshness
80
60
40
evict_below
50
35
20
on_unverifiable
fail_closed for
software_versions,
pricing_plans,
regulation_policy;
serve_annotated
otherwise
serve_annotated
serve_annotated
regen_on_stale
true
true
false
max_claims_per_response
6
8
10
max_credits_per_response
6
6
4
Guardrails: console banner. Responses carry x-cg-clock: simulated. Evidence age uses
real time because the web is real. best_before and next_check_at use clock time.
Advancing the clock cannot change facts.
Edge cases: moving backwards is allowed only through reset, and scheduled jobs are
recomputed.
AT: advance 3 days and every entry with best_before inside that window is due at its
next lookup.
3.4 Console features (F-20 to F-25)
Page layouts are in Document 2. These are the behavior rules on top.
ID
Feature
Behavior rules
F-
20
Playground
Server-side proxy adds headers and returns
response, response id and trace id. Default policy
strict. Claim highlight uses spans, falling back to
sentence highlight when spans misalign. A Copy
as curl button shows the exact headers for
developers.
F-21
Live Feed
Virtualized table that keeps 1,000 rows in memory.
Pause buffers events. Filters are applied server-
side. Row trace is fetched from GET
/api/v1/requests/{id}.
F-22
Cache Explorer
Actions call POST /api/v1/cache-
entries/{id}/revalidate, /evict and /pin. Optimistic
UI with rollback on error. Countdown uses clock
time.
F-23
Claim Inspector and Fact
Ledger
Read-only except Re-verify and Mark reviewed.
Evidence cards open the source in a new tab.
Features are shown as signed contributions.
F-24
Policies and Settings
Form validation mirrors the server schema. POST
/api/v1/policies/dry-run resolves a prompt.
Settings changes are written to events.
3.5 Evaluation, observability and safety features
F-26 Evaluation Lab (P0; FR-070 to FR-074)
1. Dataset (StaleBench-mini): about 280 items: 6 verifiable classes x 40 plus 40 static
controls. Per class: 40 percent current, 40 percent outdated, 20 percent contradicted.
Construction protocol: (a) choose entities whose attribute changed in the last 18
months, plus entities that did not change (controls); (b) ask a model with an older
knowledge cutoff and freeze its answer; (c) extract the target claim; (d) two labelers
label it current, outdated or contradicted using an official source as of label_date and
record the URL; (e) a third resolves disagreements and Cohen's kappa is reported; (f)
freeze with label_date and re-check a 10 percent sample on the final day for drift.
Minimum viable set: 120 items (20 per class).
2. Variants: B0 no check. B1 fixed-TTL cache simulation. B2 LLM self-check (ask the
model whether the claim is still current, no search). B3 verify every claim with Tavily
and the judge but without ledger, triage or priors. CG_full. Ablations: CG_no_ledger,
CG_no_triage, CG_no_prior, CG_basic_depth, CG_no_extract.
3. Metrics: the positive class is stale (outdated or contradicted). Precision, recall, F1,
AUROC and PR-AUC of (100 minus freshness), ECE with 10 bins, Brier score, abstain
rate and accuracy on non-abstained items, per-class breakdown, cost per claim
(credits, judge tokens, USD), latency p50 and p95.
4. Simulated-world workload (P1): 3,000 requests drawn from 300 prompts with a Zipf
distribution (s = 1.1) plus paraphrases, over 14 simulated days using the clock. A
scripted mock Tavily serves evidence from a world script in which 15 percent of facts
change at scheduled times. Baselines: TTL 1 h, 24 h and 7 d, verify-every-hit,
ChronoGuard strict and standard. Metrics: stale-serve rate, hit rate, retention, tokens
saved, credits, net cost, blocking-path share. This is labeled a simulation. Accuracy
claims come only from live runs.
5. Outputs: JSON and CSV export, PR curve, calibration plot, accuracy-versus-cost chart,
ablation table.
ID
Feature
Behavior rules
F-25
Costs and Latency
Reads cost_ledger and requests. A reconciliation
line shows the delta between the ledger and
provider-reported usage. USD prices come from
model_profiles and config.
Edge cases: Tavily drift between runs. Evidence snapshots are stored per run and
replay mode reuses them.
AT: a full run on 120 items finishes in under 15 minutes at concurrency 8. Replay-mode
metrics reproduce within 2 percent.
F-27 Observability (P0; FR-080, FR-081)
Prometheus metrics (names in TRD 4.11). A decision trace per request: ordered steps
with timings and reason codes, stored in requests.decision_detail. Structured JSON
logs carry request_id, cache_id, claim_id and fact_key. The Verifier exposes /healthz
and /readyz. Plugin metrics are exposed through Bifrost's metrics endpoint [verify] or
relayed by heartbeat to the Verifier.
AT: every decision type appears in metrics after the demo script.
F-28 Safety, privacy and evidence hardening (P0; FR-027, NFR-05, NFR-06)
1. Untrusted evidence: strip HTML, scripts and markdown links. Delimit evidence. Judge
instruction says evidence is data. Output is schema-constrained. Instructions inside
evidence are never executed. Regeneration receives only whitelisted fields.
2. Two-key rule before eviction (TRD 4.5.15).
3. PII: regex redaction of emails, phone numbers and ID-like numbers in claim queries.
Claims about private individuals are skipped. Only public-figure and organization
claims are verified.
4. Data minimization: store_content toggle. Evidence snippets capped at 600 characters.
Logs never hold API keys, and hold full prompts only under a debug flag.
5. Access control: per-key rate caps on the playground proxy, x-cg-internal-key on the
internal API, login on the console.
6. Source lists: a denylist of low-quality domains and an allowlist that boosts authority.
AT: 10 prompt-injection cases, a redaction test, and a no-secrets-in-logs test.
F-29 Code-aware claims (P2; FR-014)
Behavior: detect code blocks, parse imports, package names, pinned versions and calls
to known deprecated APIs through a small registry (package to version source via
Tavily Extract of registry or release pages). Emit claims in class software_versions with
attribute pinned_version or api_signature. Annotate next to the code lines. Not in the
MVP. The extractor keeps a hook for it.
AT: sample snippets with a known-deprecated call are flagged.
