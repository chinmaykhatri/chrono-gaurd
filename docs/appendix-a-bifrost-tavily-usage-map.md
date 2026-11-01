# Appendix A: Bifrost and Tavily usage map
A.1 Principle
Both sponsors must be visible in the architecture, the code, the demo and the README,
and removing either must break the product. Maxim AI is the company that builds Bifrost.
The partner poster lists Bifrost and Tavily only. If the organizers also expect Maxim's own
platform (observability, evaluation), FR-091 below is the minimum and the Eval Lab export
is the natural second step [verify what is expected].
A.2 Bifrost usage map
#
Bifrost capability
How ChronoGuard
uses it
Where
defined
Visible in the demo
as
1
Plugin system
(PreLLMHook,
PostLLMHook, HTTP
transport hooks)
cg-front and cg-back
run inside the
gateway pipeline
TRD 4.4
Settings page
shows Bifrost
version and plugin
order. x-cg-*
headers
2
Semantic cache plugin
Soft and hard expiry
through x-bf-cache-
ttl, eviction, priming,
cache-hit metadata
F-02, F-12,
F-14, F-15
Cache Explorer. Hit
badges in the Feed
3
OpenAI-compatible
HTTP gateway
Applications change
only the base URL.
The Playground sends
through it
Flow A
Copy as curl in the
Playground
4
Provider routing and
failover
Extractor, judge and
regeneration calls go
through Bifrost to any
provider
TRD 4.3
Costs page by
model
5
Virtual keys and
governance budgets
Dedicated keys for
extractor, judge and
regeneration, each
with budget and rate
limits [verify]
FR-090
Settings shows
spend per key
6
Telemetry and logging
ChronoGuard metrics
next to Bifrost's own.
Optional forwarding
of decision spans to
Maxim's observability
through Bifrost's
Maxim plugin [verify]
FR-091
Maxim dashboard
(optional)
7
Open-source
repository
In-tree plugin with
tests and docs,
upstream pull request
FR-095
Pull request link at
the end of the demo
A.3 Tavily usage map
A.4 Requirements added to the PRD (addendum to section 1.9)
#
Tavily
capability
How ChronoGuard uses it
Where
defined
Visible in the demo as
1
Search API
Core evidence: topic
(general, news, finance),
search_depth, time_range,
start_date and end_date,
include_domains,
max_results
F-08, TRD
4.5.6
Evidence cards show
the query and
parameters
2
Extract API
Primary-page content for
pricing, versions and
regulation
F-08
Evidence cards labeled
extract
3
Result
metadata
published_date, URL and
score feed the recency and
authority features
TRD 4.5.7,
4.5.9
Score breakdown bars
4
Credits
Credit accounting by class,
budgets, triage, ledger
reuse
F-06, F-07
Costs page and header
meter
5
Research or
Crawl (P2)
Deep verification when the
two-key rule is unmet
[verify availability and cost]
FR-093
Optional
6
Recorded
responses
Fixtures power tests and
the offline demo fallback
TRD 4.12
Replay badge
ID
Requirement
Pri
FR-090
Dedicated Bifrost virtual keys for extractor, judge
and regeneration traffic, each with budget and rate
limits, so ChronoGuard's own spend is governed by
Bifrost
P1
A.5 Removal test (put this in the README)
Without Bifrost: there is no place to intercept every request, no cache to control and
no single entry point. ChronoGuard has nothing to attach to.
Without Tavily: there is no live evidence. Every verdict falls back to the staleness prior
and the judge's unaided guess, so per-claim freshness would be unverifiable.
A.6 What each sponsor's engineer will look for
ID
Requirement
Pri
FR-091
Forward ChronoGuard decision spans to Bifrost's
observability path, with an optional Maxim plugin
target [verify]
P2
FR-092
Console attribution: evidence cards show Tavily as
the retrieval source with the query used. Settings
shows the Bifrost version and plugin order
P0
FR-093
Use Tavily Research or Crawl for deep verification
when the two-key rule is unmet [verify availability
and cost]
P2
FR-094
README and architecture diagram name every
Bifrost and Tavily touchpoint and include the
removal test below
P0
FR-095
Upstream-ready packaging: plugin laid out as in the
Bifrost repository, a docs page, tests, and a pull
request draft
P1
Sponsor
Likely checks
How we answer
Bifrost
An idiomatic Go plugin that follows
the repository conventions, no hot-
path regression, correct use of the
cache plugin, docs and tests,
mergeability
In-tree plugin, benchmark with a p99
delta, table-driven tests,
docs/plugin.md, upstream-ready
branch
A.7 Five demo moments that show the sponsors
1. The Playground response headers and the Bifrost cache-hit metadata on the second
request.
2. The Settings card with the Bifrost version, plugin order and virtual-key spend.
3. An evidence card with the Tavily query, the published date and the authority tier.
4. The Costs page with Tavily credits by class next to Bifrost virtual-key spend.
5. The overhead chart: plugins off versus on, measured on the Bifrost gateway.
Sponsor
Likely checks
How we answer
Tavily
Meaningful use of Search and Extract
parameters, credit efficiency,
evidence quality, an evaluation of the
freshness score, sources visible to the
user
Per-class profiles, ledger and triage
with cost numbers, tier and date
features, Eval Lab report, evidence
cards
