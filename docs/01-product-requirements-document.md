# Document 1: Product Requirements Document (PRD)
1.1 Document control
1.2 Executive summary
ChronoGuard is a pair of Bifrost plugins, a verification service and a web console. It gives
every time-sensitive claim in an LLM answer a freshness score and a best-before date, re-
verifies claims against live web evidence from Tavily when they may have gone stale, and
upgrades Bifrost's semantic cache from a blind TTL cache into a self-healing one. Cached
answers are served while their facts are fresh, revalidated when due, and evicted and
regenerated with evidence when the world has changed. Applications change nothing
except an optional header, because they already point their SDK at Bifrost.
Field
Value
Product
ChronoGuard. Tagline: best-before dates for LLM
answers
Version scope
Hackathon MVP (all P0) plus a v1 roadmap
Integrates with
Bifrost open-source gateway (Go, plugin system,
semantic cache) and Tavily Search and Extract
Problem statements
Bifrost PS 04: extend the gateway (plugin, caching
strategy, UI). Tavily PS 01: flag stale claims, re-verify
live, freshness score per claim
Roles
Gateway lead (Go), Verifier lead (Python, AI),
Console lead (React, evaluation). See Document 5
The edge is not detection alone, since many teams will build a claim checker. The edge is
the combination of: (1) a fact-level ledger that shares one verification across every answer
that mentions the same fact, (2) cache decisions driven by facts instead of clocks, (3) a
budget scheduler that spends Tavily credits only where staleness is likely and valuable,
and (4) published measurements: precision, recall, calibration, overhead and net cost.
1.3 Problem statement
P1. Training-cutoff staleness
A model states prices, versions, officeholders and rules as they were in its training data.
The first answer can already be wrong, and it is delivered with full confidence.
P2. Cache decay
Gateway caches store answers under a TTL that a human guesses per request. Bifrost's
semantic cache accepts a TTL per request (for example 30 seconds for dynamic content
and an hour for stable content). A short TTL destroys the savings that justify caching. A
long TTL serves stale facts, and one stale answer is then served to every similar query. The
TTL knows nothing about whether the cached facts changed.
P3. No visibility or accounting
Operators cannot see which claims in which cached answers are at risk, why an answer
was trusted, or what verification costs compared with what caching saves.
Why the obvious fixes fail
Approach
Fresh?
Keeps
cache
savings?
Cost
Gap
Fixed TTL (today)
By luck
Partly
None
Blind to whether facts
changed
No cache
Only if
search is
added
No
Highest
Full price every time
Search on every
request (RAG)
Mostly
No
High
Latency, no per-claim
visibility
1.4 Vision and core ideas
Vision: best-before dates for LLM answers, enforced at the gateway.
1. Every claim has an expiry. Claims are classified by volatility (pricing and versions
decay in days, geography in years). Each gets a freshness score and a best-before date.
2. The cache decides with facts, not clocks. Soft expiry (best_before) is separate from
hard expiry (the Bifrost TTL). At best_before the cache revalidates instead of
discarding. When a fact is proven outdated, every cached answer that mentions it is
invalidated at once.
3. Verification is a shared, budgeted resource. One verified fact is reused by every
answer and cache entry that mentions it (Fact Ledger). Concurrent requests share one
Tavily lookup (singleflight). A scheduler ranks claims by staleness probability,
importance, popularity and cost.
1.5 Goals and non-goals
Goals
G1: Stop stale facts from being served from cache, and flag them on first generation.
G2: Keep at least 85 percent of cache hits compared with a no-verification long-TTL
cache.
G3: Zero application code changes. Clients keep their OpenAI-compatible SDK against
Bifrost.
G4: Per-claim transparency: score, evidence, dates and the reason for every decision.
G5: Bounded cost. Verification spend stays below the generation spend it saves.
Approach
Fresh?
Keeps
cache
savings?
Cost
Gap
Verify on every
cache hit
Yes
Partly
High
Verification cost
erases savings
LLM self-check
No
n/a
Low
A model cannot know
what changed after
training
ChronoGuard
Yes, with
evidence
Yes
Bounded by
budgets
This product
G6: Proof. Publish precision, recall, calibration, overhead and cost from a reproducible
evaluation.
Non-goals
NG1: Fact-checking opinions, reasoning, creative text or personal data.
NG2: Guaranteeing truth. ChronoGuard reports freshness and evidence confidence,
not certainty.
NG3: Replacing retrieval-augmented generation for knowledge-base answers.
NG4: Real-time data such as tick-level prices. Those prompts bypass the cache.
NG5: Multi-tenant SaaS, billing and SSO (roadmap only).
NG6: Verifying images, audio or tool calls.
NG7: Training or fine-tuning models.
1.6 Personas
Names are illustrative.
Persona
Needs
Success looks like
Priya, platform engineer
who runs Bifrost
Safe defaults, budgets, kill
switch, low overhead
Enables it with two config
entries and sees no latency
regression
Dev, application
developer
Correct current answers with
no code changes
Asks for a latest version and
gets the current one with a
source
Maya, AI product and
FinOps owner
Proof that verification pays for
itself
Reads net savings per day and
per class
Judge, Bifrost or Tavily
engineer
A mergeable plugin, clean
architecture, honest numbers
Runs the demo, reads the
benchmark, sees a PR-ready
repo
1.7 User stories and acceptance criteria
ID
Story
Acceptance criteria
US-
01
As Priya, I enable ChronoGuard with
two plugin entries so applications are
unaffected.
A sample OpenAI-SDK app works
unchanged. Responses carry x-cg-*
headers. Setting enabled=false or sending
x-cg-mode: off restores baseline behavior.
US-
02
As Dev, I ask a time-sensitive question
under the strict policy and get a
freshness score and sources per
claim, with stale claims corrected.
Per-claim scores returned inline. Outdated
claims show corrected value and source
URL. Blocking budget respected (default
4.5 s); an exceeded budget degrades per
policy.
US-
03
As Dev, a similar question later is
answered from cache instantly while
its facts are fresh.
Hit overhead p99 <= 3 ms. Zero Tavily calls
while every claim is inside its
next_check_at. Annotation shows fresh
scores.
US-
04
As Dev, when a fact changed in the
world I get a corrected answer after
the entry becomes due.
Due entry triggers revalidation. An
outdated verdict evicts the entry and
returns a regenerated answer with
evidence. The next request hits the
corrected entry.
US-
05
As Priya, I see due and stale entries
and can revalidate or evict them
manually.
Cache Explorer lists status and a best-
before countdown. Manual actions take
effect within 5 s and are logged.
US-
06
As Priya, I set policy per volatility
class and per virtual key, and a strict
route fails closed when it cannot
verify.
Rules resolve by priority. Strict with
on_unverifiable=fail_closed returns a clear
error code and never a stale answer for
pricing, version and regulation classes.
US-
07
As Maya, I see net savings: generation
cost avoided by hits minus
verification cost, by day and class.
Costs page shows saved, spent and net
with ledger drill-down. Totals reconcile
with cost_ledger within 1 percent.
US-
08
As Dev, I inspect any claim and see
evidence, dates, domains, judge
rationale and score breakdown.
Claim Inspector shows the top 3 evidence
items with publish dates, authority tiers
and feature contributions.
1.8 Scope (MoSCoW)
Must (P0): plugin pair, claim extraction, volatility classes, Fact Ledger, Tavily
verification, judge, freshness score, decision engine (serve, SWR, blocking revalidate,
evict and regenerate), cascade invalidation, per-claim annotations, strict and standard
policies, simulated clock, Playground, Live Feed, Cache Explorer, Claim Inspector,
Costs page, Evaluation Lab with labeled dataset and baselines, overhead benchmark,
metrics and decision traces.
Should (P1): adaptive intervals, refresh-ahead, model-cutoff priors, stream
annotations, repair mode, policy editor, Fact Ledger view, legacy cache ingestion,
simulated-world workload.
Could (P2): buffer-and-release streaming, code-aware claims, fuzzy entity aliases,
Grafana bundle, OpenTelemetry, upstream pull request to Bifrost.
ID
Story
Acceptance criteria
US-
09
As Dev, I stream responses and
ChronoGuard never breaks the
stream.
Streams pass through unchanged.
Annotations arrive via URL or SSE. Time to
first token grows by no more than 1 ms at
p99.
US-
10
As Priya, I set budgets and the system
degrades gracefully when they run
out.
On exhaustion: basic search depth, then
fewer claims, then SWR or unverified
annotation per policy. Console shows a
budget_exhausted event.
US-11
As Maya, when one fact is found
outdated every cached answer
mentioning it is invalidated at once.
Cascade marks all referencing entries
stale within 2 s of the verdict. Hot entries
are regenerated ahead of the next hit.
US-
12
As a judge, I run a three-minute demo
using a simulated clock.
The Document 2 demo script passes end
to end. Clock changes are labeled
Simulated in the UI and in responses.
US-
13
As a researcher, I run the evaluation
with baselines and export metrics.
Eval Lab reports precision, recall, F1,
AUROC, ECE, Brier, cost and latency per
variant, with JSON and CSV export.
US-
14
As Priya, I measure plugin overhead
with a benchmark harness.
Harness runs identical load with plugins
off and on and reports p50, p95 and p99
deltas.
Won't (this version): multi-tenancy, SSO, non-chat endpoints (embeddings, responses
API), tool-call verification.
1.9 Functional requirements
Interception and ingestion
Claim processing
ID
Requirement
Pri
FR-001
Run as a Bifrost plugin pair in the HTTP gateway.
Applications need no change beyond the existing
base URL and optional x-cg-* headers.
P0
FR-002
On a cache miss, capture request and response
and hand them to the verifier without delaying the
response (async policies).
P0
FR-003
On a cache hit, load the claim manifest and choose
an action within the NFR-01 budget.
P0
FR-004
Ingest legacy cache hits that have no manifest
(origin legacy_cache).
P1
FR-005
Kill switches: global enabled flag and per-request
x-cg-mode: off. Plugin code recovers from panics
and never fails a request.
P0
ID
Requirement
Pri
FR-010
Extract atomic verifiable claims with text span,
entity, attribute, stated value, importance and any
as-of date hint.
P0
FR-011
Assign one of eight volatility classes with
configurable half-life, soft TTL and recheck
interval.
P0
FR-012
Normalize each claim to a fact key and keep a Fact
Ledger shared across responses and cache entries.
P0
Verification and scoring
ID
Requirement
Pri
FR-013
Skip opinions, procedures, definitions and
personal-data claims, recording the reason.
P0
FR-014
Code-aware claims: libraries, API signatures,
pinned versions, deprecated calls.
P2
ID
Requirement
Pri
FR-020
Retrieve live evidence with Tavily Search using a
per-class profile, and Extract on primary pages
when configured.
P0
FR-021
Produce a verdict (confirmed, outdated,
contradicted, unverifiable) with corrected value
and evidence references.
P0
FR-022
Compute a per-claim freshness score from 0 to 100
and an evidence confidence, and store the feature
breakdown.
P0
FR-023
Reuse ledger verdicts and coalesce concurrent
lookups so one fact costs one verification per
validity window.
P0
FR-024
Triage claims by staleness probability, importance,
popularity and cost under per-response and global
budgets, degrading gracefully.
P0
FR-025
Adapt recheck intervals: lengthen after
confirmations, shorten after a detected change.
P1
FR-026
Use the model knowledge cutoff as the claim as-of
date for provider-generated answers.
P1
FR-027
Treat retrieved text as untrusted. Strict-mode
eviction requires the two-key evidence rule (TRD
4.5.15).
P0
Cache control
Annotation and API
ID
Requirement
Pri
FR-030
Compute best_before (soft expiry) and a longer
hard TTL, and set the hard TTL on caching
requests.
P0
FR-031
Decision engine with actions: serve, serve_swr,
revalidate_blocking, evict_regen, evict_lazy,
fail_open, fail_closed, bypass.
P0
FR-032
Evict entries through Bifrost cache invalidation by
cache or request id.
P0
FR-033
Cascade: when a fact is outdated, mark every
entry that mentions it stale.
P0
FR-034
Regenerate the triggering request with evidence
and re-cache the corrected answer under the
original key.
P0
FR-035
Refresh-ahead: revalidate or regenerate hot
entries before they are next requested.
P1
FR-036
Bypass the cache for realtime-class prompts.
P0
ID
Requirement
Pri
FR-040
Return per-claim freshness annotations: inline
under verify_before_return, otherwise through an
annotation URL and SSE.
P0
FR-041
Add response headers x-cg-response-id, x-cg-
decision, x-cg-freshness and x-cg-cache.
P0
FR-042
Streams pass through unchanged. Annotations
arrive asynchronously.
P1
FR-043
Buffer-and-release streaming for the strict policy.
P2
Policies
Console
ID
Requirement
Pri
FR-044
Repair mode: when stale claims are found on a first
generation, regenerate with evidence and cite
sources.
P1
ID
Requirement
Pri
FR-050
Policies strict, standard and lenient with per-class
overrides, selected by header, virtual key or rule.
P0
FR-051
on_unverifiable behavior: serve_annotated or
fail_closed.
P0
FR-052
Hot reload of policies and class settings without
restart.
P1
ID
Requirement
Pri
FR-060
Playground with claim highlights and a decision
trace.
P0
FR-061
Live Feed of requests and decisions.
P0
FR-062
Cache Explorer with revalidate and evict actions.
P0
FR-063
Claim Inspector with evidence and score
breakdown.
P0
FR-064
Fact Ledger view with cascade impact.
P1
FR-065
Costs and Latency page.
P0
FR-066
Policy and class editor.
P1
FR-067
Simulated clock for demos and evaluation, clearly
labeled.
P0
FR-068
Evaluation Lab.
P0
Evaluation and observability
1.10 Non-functional requirements
ID
Requirement
Pri
FR-069
Settings and connection health.
P1
ID
Requirement
Pri
FR-070
Import, export and version the labeled dataset.
P0
FR-071
Run baselines B0 to B3 and ChronoGuard
ablations.
P0
FR-072
Report precision, recall, F1, AUROC, ECE, Brier,
cost and latency.
P0
FR-073
Benchmark harness comparing plugins off and on.
P0
FR-074
Simulated-world workload for cache economics.
P1
FR-080
Prometheus metrics for every stage.
P0
FR-081
Decision trace stored per request.
P0
FR-082
OpenTelemetry traces.
P2
ID
Requirement
Target
NFR-
01
Overhead of plugin work on the cache-
hit path, excluding network verification
p50 <= 1 ms, p99 <= 3 ms at 300
requests per second
NFR-
02
Isolation: a ChronoGuard fault must
never fail or slow the gateway beyond
configured budgets
Panic recovery, timeouts, circuit
breakers, fail-open default
NFR-
03
Verifier throughput
20 concurrent verifications, Tavily
concurrency capped at 8, HTTP 429
handled with backoff
NFR-
04
Cost control
Per-response and per-hour credit and
token budgets enforced before any call
ID
Requirement
Target
NFR-
05
Security
Keys only in environment, internal API
key header, evidence treated as
untrusted data (TRD 4.10)
NFR-
06
Privacy
Queries built from claims, PII redaction,
personal-data claims skipped, 7-day
retention by default
NFR-
07
Compatibility
OpenAI-compatible chat completions
through the Bifrost HTTP gateway,
stream and non-stream. Other
endpoints untouched
NFR-
08
Reproducibility
Temperature 0, pinned model ids,
stored evidence snapshots, seeded
workloads
NFR-
09
Observability
Every decision explainable from a
stored trace plus Prometheus metrics
and structured logs
NFR-
10
Operability
docker compose up starts every
service and loads seed data
NFR-11
Usability
The console is understandable in 60
seconds: status colors, plain decision
labels, empty and error states on every
page
NFR-
12
Maintainability
Thin plugin, decision engine as a pure
function with table-driven tests
1.11 Success metrics
ID
Metric
Definition
Target (hypothesis)
Measured by
M1
Stale-claim
detection
Precision and recall of
the stale flag
(outdated or
contradicted) against
human labels on
StaleBench-mini
Recall >= 0.85 at
precision >= 0.80
Eval Lab, live
Tavily
M2
Calibration
Expected calibration
error of the freshness
score, 10 bins
ECE <= 0.10 after
calibration
Eval Lab
M3
Stale-serve
rate
Share of served
answers containing a
claim that is stale at
serve time, on the 14-
day simulated
workload
At least 80 percent
below the TTL=24h
baseline; under 2
percent absolute for
the strict policy
Simulated-
world workload
M4
Cache
retention
Hit rate relative to a
no-verification TTL=7d
cache
>= 85 percent
Simulated-
world workload
M5
Net cost
Generation cost
avoided by hits minus
Tavily credits and
judge tokens
Net positive and at
least 35 percent
below the verify-
every-hit baseline
cost_ledger
M6
Hot-path
overhead
Latency added by
plugins on cache hits,
excluding network
verification
p50 <= 1 ms, p99 <= 3
ms at 300 RPS
Benchmark
harness
M7
Verification
latency
Ingest to verdict
(async), and share of
strict misses finished
inside the blocking
budget
p50 <= 6 s async; >=
85 percent inside 4.5
s for answers with <=
3 time-sensitive
claims
Request log
1.12 Traceability to the two problem statements
ID
Metric
Definition
Target (hypothesis)
Measured by
M8
Ledger reuse
Share of claim
verifications served
from the ledger or
coalesced
>= 40 percent on the
simulated workload
verifications
table
M9
Tavily cost
Credits per 100
answered requests, by
class
Reported; budget cap
honored 100 percent
of the time
cost_ledger
M10
Explainability
Stale decisions
carrying at least one
evidence link and a
rationale
100 percent
Decision traces
Problem statement text
ChronoGuard answer
Requirements
Bifrost 04: something
operators would miss if you
took it away
A plugin pair that turns the
cache from clock-driven to
fact-driven, with a console
FR-001, FR-030 to FR-036,
FR-060 to FR-069
Bifrost 04: plugin,
integration, UI, routing or
caching strategy, developer
tool
Plugin: yes. Caching strategy:
yes (soft and hard expiry,
cascade). UI: yes. Developer
tool: benchmark harness and
Eval Lab
FR-073
Tavily 01: a layer that takes
any LLM answer
Gateway placement covers
any provider and any app.
First-generation answers are
verified, not only cached ones
FR-002, FR-010, FR-040
Tavily 01: flags claims likely
to have gone stale
Volatility classes, model-
cutoff-aware prior, triage
FR-011, FR-024, FR-026
Tavily 01: re-verifies against
live sources
Tavily Search and Extract with
class profiles, evidence
stored and linked
FR-020, FR-021
1.13 Dependencies, assumptions and constraints
A Tavily API key and credits are available. The event advertises credits for builders;
confirm the amount and whether they cover evaluation runs.
LLM provider keys are reachable through Bifrost for the extractor, judge and
regeneration.
The Bifrost version is pinned on Day 0 and the Go toolchain matches it (the plugin docs
require the same Go version for shared-object plugins).
The semantic cache needs a vector store set up as Bifrost documents it (Weaviate in
the documentation reviewed) [verify supported stores].
Build window and team size are unknown at the time of writing. Document 5 gives 24-
hour and 48-hour plans.
The demo needs internet access. Replay fixtures and a backup video cover outages.
1.14 Risks
Problem statement text
ChronoGuard answer
Requirements
Tavily 01: freshness score
per claim
Calibrated 0 to 100 score with
feature breakdown
FR-022, FR-040
ID
Risk
Likelihood /
impact
Mitigation
R-01
Plugin ordering or cache-hit
visibility differs from the docs
Medium / High
Day-0 spikes S1 to S4. Plan B
designs in TRD 4.5.14
R-
02
Tavily latency, rate limits or
credits constrain the demo
Medium / High
Basic depth by default, ledger
reuse, budgets, rehearsed
prompts, replay fixtures
R-
03
Judge errors cause false
evictions
Medium / High
Two-key evidence rule,
calibration, confidence
thresholds, review list,
measured false-alarm rate
R-
04
Scope creep
High / High
P0 list frozen at hour 12. Cut
lines in Document 5
1.15 Release plan
v0.1 (hackathon): all P0 requirements.
v0.2 (week after): all P1 requirements.
v1.0: upstream contribution to Bifrost (plugin and docs), Bifrost UI integration, multi-
tenancy, connectors for private evidence sources, Grafana dashboards, buffer-and-
release streaming.
1.16 Open questions
Q1: Does a combined entry compete in both prize pools, and what is the judging rubric?
Q2: How long is the build window and how large is the team?
Q3: Which providers, models and API credits are available for the extractor, judge and
regeneration?
Q4: Is a Bifrost version pinned by the organizers?
Q5: What is the submission format: repository, demo video, pull request, slides?
Q6: Can the Tavily credit grant be used for evaluation runs?
ID
Risk
Likelihood /
impact
Mitigation
R-
05
Go and Bifrost internals slow
the team down
Medium / High
Thin Go plugin, logic in the
Python verifier, in-tree build,
spike first
R-
06
Demo fragility (web changes,
outages)
Medium / High
Rehearsed prompts with
fallbacks, simulated clock,
backup video
R-
07
Semantic cache needs a vector-
store setup
Medium /
Medium
Docker Compose service.
Confirm supported stores in S7
R-
08
Eligibility of combined entries
unclear
Medium /
Medium
Ask organizers. The Bifrost
track is the spine either way
R-
09
Labeling the evaluation dataset
takes too long
High / Medium
Start on day one in parallel.
Minimum viable set is 120 items
R-10
User prompts leak to a third
party through search queries
Low / High
Queries built from extracted
claims only, PII redaction,
personal-data claims skipped
1.17 Glossary
Term
Meaning
Claim
One atomic, checkable statement extracted from
an answer
Fact
The normalized subject-attribute pair a claim is
about, identified by a fact key. Many claims can
map to one fact
Fact Ledger
Shared record of the latest verdict, value and
validity window for each fact
Claim manifest
Per-cache-entry record of claims, statuses,
best_before and next_check_at, kept in Redis for
the hot path
best_before
Soft expiry. When reached, the entry is revalidated,
not discarded
Hard TTL
Longer expiry set on the Bifrost cache so entries
live long enough to be revalidated
SWR
Serve-while-revalidate: serve now, verify in the
background
Strictness
Policy level (strict, standard, lenient) controlling
blocking and thresholds
Verdict
confirmed, outdated, contradicted or unverifiable
Freshness score
Calibrated 0 to 100 estimate that a claim is current
now
Evidence confidence
How strongly the retrieved evidence supports the
verdict, separate from freshness
Singleflight
Coalescing concurrent lookups for the same fact
into one
Cascade invalidation
Marking every cache entry that mentions an
outdated fact as stale
Grounded regeneration
Regenerating an answer with verified evidence
injected
