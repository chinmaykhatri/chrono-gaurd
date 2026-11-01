# Document 5: Implementation Plan
5.1 Assumptions and team roles
The build window and team size are unknown. This plan gives a 48-hour plan, a 24-hour
cut list, and role splits for 2, 3 or 4 people.
Tools: one GitHub repository, Docker, shared Tavily and provider keys, a shared chat
channel.
The P0 scope freezes at hour 12 of the 48-hour plan. Anything new after that replaces
something else.
Team of 2: Person A takes E1 plus the benchmark. Person B takes E2 plus evaluation. The
console is limited to three pages (Playground, Live Feed, Cache Explorer) built by
whoever is free, and the dataset is 120 items. Team of 4: add E4 for dataset, evaluation, QA
and documentation, so E3 can finish Playground and Cache Explorer earlier.
5.2 Phases and milestones (48-hour plan)
Role
Owns
Skills
E1 Gateway lead
Bifrost fork, cg-front, cg-back, decision
engine, benchmark harness
Go, Docker
E2 Verifier lead
Verifier pipeline, Tavily, judge, scoring,
ledger, regeneration orchestration, eval
runner
Python, LLM
prompting
E3 Console and
evaluation lead
Console, dataset labeling lead, demo,
documentation
React, TypeScript,
writing
Everyone
Dataset labeling, demo rehearsal
Care and patience
Phase
Hours
Goal
Exit milestone
P0 Setup and
spikes
0 to 4
Stack runs. Assumptions
verified
Spike report. Plan A, A2 or B
chosen and recorded
P1 Walking
skeleton
4 to 14
A request flows end to end
M1: ask through Bifrost and
see extracted claims in the
Live Feed
5.3 Work breakdown
Hours are shown as full / lean. Lean is the scope to build when time is short.
Phase
Hours
Goal
Exit milestone
P2 Verification
core
14 to 26
Claims verified and scored
M2: strict policy returns
inline per-claim scores on an
uncached answer
P3 Cache loop
26 to 36
Decisions, revalidation,
cascade, regeneration
M3: the full demo loop
works (miss, hit, due, evict
and regenerate, cascade)
P4 Evaluation
30 to 42
(parallel)
Numbers
M4: Eval Lab report and
overhead benchmark exist
P5 Polish and
demo
42 to 48
Demo ready
M5: dress rehearsal passes
twice, video recorded,
submission sent
ID
Work package
Owner
Hours
Depends
on
Done when
WP-
01
Compose stack: Bifrost fork
build, Redis, Postgres,
Weaviate, env wiring
E1
3 / 3
none
docker compose up serves chat
completions with the semantic
cache on
WP-
02
Spikes S1 to S5 and S7
E1
4 / 3
WP-01
Spike report committed
WP-
03
Spike S6 (Tavily probe) and S8
(prompt prototypes)
E2
3 / 2
none
Latency and credit table. 10-
sample prompt results
WP-
04
Repo scaffolding, CI (lint,
tests), Makefile
E3
2 / 1
none
CI green
WP-
05
cg-front skeleton: HTTP pre-
hook classifier, cache headers,
PostLLMHook ingest
E1
6 / 5
WP-02
Ingest messages reach the
Verifier
WP-
06
Verifier skeleton: FastAPI,
Alembic migrations, Redis,
ingest endpoint
E2
4 / 3
WP-03
/internal/v1/ingest persists a
response
WP-
07
Claim extraction, normalization,
fact keys
E2
6 / 5
WP-06
F-04 and F-05 acceptance tests
pass
ID
Work package
Owner
Hours
Depends
on
Done when
WP-
08
Console shell: auth, layout, SSE
hook, Live Feed
E3
6 / 4
WP-06
Feed shows live requests
WP-
09
Tavily client, query synthesis,
evidence normalization
E2
5 / 4
WP-03
F-08 tests pass
WP-
10
Judge, scoring v0, two-key rule
E2
6 / 5
WP-09
F-09 and F-10 tests pass
WP-11
Fact Ledger, singleflight,
budgets, triage
E2
5 / 3
WP-10
F-06 and F-07 tests pass
WP-
12
Manifest builder, Redis write,
cache entry records
E2
3 / 2
WP-11
F-11 tests pass
WP-13
Decision engine (pure Go) with
table tests
E1
4 / 3
WP-05
F-12 tests pass
WP-
14
Inline verify path (strict),
annotations and headers
E1, E2
6 / 5
WP-12, WP-
13
M2
WP-
15
Playground and Claim
Inspector
E3
10 / 7
WP-14
Claims highlighted with evidence
WP-
16
Revalidation: SWR and blocking
(refresh-ahead only if time)
E1, E2
6 / 4
WP-14
F-13 passes
WP-17
Eviction, cascade, cache clear
integration
E2, E1
5 / 3
WP-16
F-14 passes
WP-
18
Grounded regeneration (Plan
A, A2 or B) and cg-back
E1, E2
8 / 5
WP-17
F-15 passes. M3
WP-
19
Simulated clock
E1, E2
3 / 2
WP-12
F-19 passes
WP-
20
Cache Explorer and Costs page
E3
8 / 5
WP-17
Pages live
WP-
21
Dataset labeling (target 280,
minimum 120)
All
12 / 8
Starts at
hour 4
Dataset frozen
WP-
22
Eval runner, baselines B0 to B3,
metrics, calibration
E2
10 / 7
WP-10, WP-
21
M4 metrics
WP-
23
Eval Lab UI
E3
6 / 4
WP-22
Report page works
WP-
24
Overhead benchmark harness
E1
4 / 3
WP-14
p50, p95, p99 deltas recorded
WP-
25
Simulated-world workload and
mock Tavily (P1)
E2
6 / 0
WP-19, WP-
22
Economics chart
Capacity check (be honest): full scope is about 154 person-hours (148 without WP-25).
Lean scope is about 106. Three people over 48 hours at roughly 70 percent productive
time give about 100 hours. So build lean, and treat everything beyond lean as a bonus. A
24-hour window needs the cut list in section 5.4.
5.4 Schedules and the 24-hour cut list
48-hour schedule (3 people)
ID
Work package
Owner
Hours
Depends
on
Done when
WP-
26
Hardening: failure paths, kill
switch, logs, metrics
E1, E2
5 / 3
WP-18
Flow F cases pass
WP-
27
Docs: README, architecture
diagram, benchmark write-up
E3
4 / 3
WP-22, WP-
24
Repository ready
WP-
28
Demo rehearsal twice, backup
video, submission
All
4 / 4
WP-26
M5
Hours
E1 Gateway
E2 Verifier
E3 Console and
evaluation
Milestone
0 to 4
WP-01, WP-02
(spikes)
WP-03 (Tavily
probe, prompt
prototypes)
WP-04 scaffold, start
WP-21 dataset
Spike report,
plan chosen
4 to 14
WP-05 cg-front,
WP-13 decision
engine
WP-06, WP-07,
start WP-09
WP-08 shell and Live
Feed, dataset
M1
14 to
26
WP-14 with E2,
start WP-24
Finish WP-09, WP-
10, WP-11, WP-12
WP-15 Playground
and Inspector,
dataset
M2
26 to
36
WP-16, WP-17,
WP-18 with E2,
WP-19
Verifier side of WP-
16 to WP-18, start
WP-22
WP-20 Cache
Explorer and Costs.
Dataset frozen at
hour 30
M3
36 to
42
WP-24
benchmark run,
WP-26
Finish WP-22,
calibration
WP-23 Eval Lab UI
M4
24-hour window: keep and cut (about 55 person-hours)
5.5 Day-0 spikes
Each spike produces one page in docs/spikes.md: the question, the result, a log excerpt as
evidence, and the decision. Total time: about 8 hours across two people.
Hours
E1 Gateway
E2 Verifier
E3 Console and
evaluation
Milestone
42 to
48
Hardening,
rehearsal
Write-up inputs,
rehearsal
WP-27 docs, backup
video
M5
Keep
Cut
Spikes S1, S2, S3, S6 (2 hours)
Fact Ledger page, Policies page (use YAML),
Costs page (one summary card)
cg-front minimal, decision engine, ingest
Adaptive intervals, refresh-ahead, eager
cascade regeneration (lazy only)
Extraction, Tavily, judge, fixed-weight
scoring, ledger and singleflight
Plan A and A2 (use Plan B), repair mode,
stream annotations
Manifest, strict inline verification, SWR and
blocking revalidation
Calibration fitting (report ECE only),
simulated-world workload
Eviction with Plan B regeneration, simulated
clock
OpenTelemetry, Grafana, ablations
Playground, Live Feed, Cache Explorer with
revalidate and evict buttons
120-item dataset, baselines B0, B2, B3 and
CG_full, precision, recall, F1, ECE
Overhead benchmark
ID
Question (checks)
Method
Pass criteria
S1
Plugin order and cache-
hit visibility (V1, V8, V9)
Build a trivial plugin pair
that logs every hook.
Register front, cache, back.
Send a miss then a hit
front PostLLMHook sees
hit metadata. back hooks
do not run on a hit. State
set in HTTP hooks is
readable in LLM hooks
S2
Cache identifiers and
clearing (V1, V2, V3)
Inspect hit metadata. Clear
by request id and by key.
Repeat the request
A specific entry can be
evicted and the next
request misses
S3
Header TTL and bypass
from the HTTP pre-hook
(V4)
Set x-bf-cache-ttl to 10 s in
the pre-hook. Strip x-bf-
cache-key for a second
request
Entry expires on time.
Stripped request
bypasses the cache
S4
Regeneration and priming
(V2, V5, V6)
Plan A: loopback with x-cg-
ground-id. Plan A2: short-
circuit store. Measure
write delay
Choose A2, A or B and
record it. Corrected
answer is returned for a
paraphrase afterwards
S5
Streaming (V10)
Log what PostLLMHook
receives for a stream. Try
the chunk hook
Ingestion at stream end is
feasible, or fall back to
accumulating chunks
S6
Tavily probe
20 queries across classes.
Record latency at basic
and advanced depth,
credits used,
published_date coverage,
Extract latency
p50 basic under 2 s and
advanced under 5 s, else
adjust blocking budgets
S7
Semantic cache setup
(V7)
Bring up the cache with its
vector store. Test a
paraphrase hit
Paraphrase returns a hit
S8
Prompt prototypes
Extractor on 10 answers,
judge on 10 evidence sets
Valid JSON at least 95
percent of the time.
Verdicts look sane
5.6 Repository structure and branching
chronoguard/
  bifrost/                      # fork, with plugins/chronoguard
    plugins/chronoguard/
      front/  back/  
internal/{classify,manifest,decide,annotate,clock,verifierclient}/
  verifier/
    
app/{api,pipeline,ledger,triage,tavily,judge,scoring,regen,eval,clock,events}
/
    migrations/  tests/
  console/
    src/{pages,components,hooks,api}/
  deploy/   docker-compose.yml  chronoguard.yaml  config.json  prometheus.yml
  eval/     dataset/  world_scripts/  reports/
  docs/     architecture.md  spikes.md  benchmark.md  demo-script.md
  Makefile  README.md
Branching: trunk-based with short-lived feature branches, one reviewer per pull request,
squash merge, CI runs lint and tests. After hour 36 main must always be demo-able. Tag
v0.1-demo for the submission.
5.7 Quality gates
Gate
When
Criteria
G1 Spike gate
Hour 4
All spike decisions recorded
G2 Scope freeze
Hour 12
P0 list final. New work replaces old work
G3 M2 gate
Hour 26
Strict inline demo works on 3 different prompts
G4 M3 gate
Hour 36
Full loop passes a demo-script dry run
G5 Evaluation gate
Hour 42
Dataset frozen, report generated
G6 Release gate
Hour 46
CI and integration suite green, overhead recorded,
backup video done
5.8 Demo preparation
Six candidate prompts, re-verified the day before, with expected outputs written
down.
make demo-reset script (clears cache, manifests, ledger, clock) and seeded entries for
the cascade scene, made from real answers.
Replay fixtures for Tavily and the fake-LLM mode as fallback.
A second machine with the stack running, and a phone hotspot in case the venue
network fails.
Two full timed rehearsals. Roles: presenter and operator.
Likely judge questions, with prepared answers: (1) How is this different from a short
TTL? (2) What does it cost? (3) What if Tavily is wrong? (two-key rule) (4) What is the
latency impact? (benchmark) (5) Does it work with streaming? (6) Why a sidecar? (7)
How do you know the score is calibrated? (8) What about private facts? (connectors
roadmap) (9) How does it scale? (10) Can this be upstreamed? (pull request plan)
5.9 Submission checklist
Public repository with a license (check compatibility with Bifrost's license) and a
README: problem, architecture diagram, five-minute run guide, results.
Three-minute demo video, evaluation report, benchmark write-up, screenshots.
Problem statement mapping page (PRD 1.12) and the sponsor usage map (Appendix A).
Upstream-ready branch or pull request draft for Bifrost.
Known limitations stated honestly.
Credits: built on Bifrost by Maxim AI and Tavily.
5.10 Cut order and stop-ship criteria
When behind, cut in this order: (1) simulated-world workload, (2) Policy editor UI, (3) Fact
Ledger UI, (4) Costs charts (keep the cards), (5) refresh-ahead, (6) adaptive intervals, (7)
repair mode, (8) Plan A2, (9) calibration fitting (keep the ECE report), (10) ablations (keep
B0 to B3 and CG_full).
Never cut: strict inline per-claim scores on an uncached answer, SWR and blocking
revalidation, eviction with a corrected answer, the dataset with precision and recall, the
overhead benchmark, the demo rehearsal.
Stop-ship criteria: any panic on the hot path, a stale answer served under strict in tests,
secrets in logs, or the demo script failing twice in rehearsal.
5.11 Post-hackathon roadmap
Week 1: all P1 items and the upstream pull request.
Month 1: multi-tenancy, Bifrost UI integration, private evidence connectors, Grafana
bundle.
Later: freshness-aware routing through PreRequestHook (route time-sensitive
prompts to search-grounded models), buffer-and-release streaming, entity graph,
hosted offering.
