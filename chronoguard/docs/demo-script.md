# ChronoGuard — 3-Minute Live Demo Script & Rehearsal Guide

## Pre-Flight Checklist (10 Minutes Prior)
1. Stack health check: Visit `http://localhost:8080/settings` — confirm Postgres, Redis, Tavily, and Model providers show green status.
2. Run reset:
   ```bash
   make demo-reset
   ```
3. Open two browser windows:
   - Window 1: **ChronoGuard Console** (`http://localhost:8080`) on Playground / Live Feed.
   - Window 2: **Settings** page (`http://localhost:8080/settings`) for clock advancement.

---

## The Six Candidate Prompts

### Primary Demo Sequence Prompts

| # | Category | Prompt | Expected Model Blindspot | Ground Truth / Live Evidence |
|---|---|---|---|---|
| **P1** | `software_versions` | *"What is the latest stable release of React and its key feature?"* | Claims React 18.2 (Server Components experimental) | React 19.x is stable (Actions, useActionState, Document Metadata) |
| **P2** | `software_versions` | *"What version of Python is the current active release?"* | Claims Python 3.11 or 3.12 | Python 3.13 is current active stable release (experimental free-threading) |
| **P3** | `pricing_plans` | *"How much does ChatGPT Plus cost per month?"* | May hallucinate outdated tier | $20/month (Confirmed current; demonstrates zero-latency cache preservation) |
| **P4** | `org_people` | *"Who is the CEO of Twitter?"* | Claims Elon Musk is CEO of Twitter | Linda Yaccarino is CEO; company rebranded to X Corp |
| **P5** | `regulation_policy` | *"Has the European Union AI Act entered into legal force?"* | Claims proposed draft under negotiation | Entered into force August 2, 2024 (Regulation 2024/1689) |
| **P6** (Control) | `static` | *"What is the speed of light in vacuum and the formula for energy?"* | Settled physical constant | $c \approx 299,792,458\text{ m/s}$, $E=mc^2$. **Zero Tavily calls triggered**. |

---

## 3-Minute Demo Narrative (Minute-by-Minute)

### Minute 0:00 – 0:45 | Scene 1: The First Answer (Cache Miss & Manifest Creation)
- **Action**: Paste **P1** into Playground (`policy: strict`, `cache: true`). Click **Send**.
- **What is happening**:
  1. Bifrost generates answer via upstream provider.
  2. ChronoGuard `cg-front` intercepts post-LLM response.
  3. Strict policy runs inline verification: extracts atomic claim `[React, latest_version, 18.2]`, classifies as `software_versions` (half-life: 21 days).
  4. Tavily search retrieves official `react.dev` release notes.
  5. 2-Key Rule evaluates evidence: contradicts stated "18.2", identifies "19.0.0".
  6. Response returned with `x-cg-decision: passthrough` and full claim manifest stored in Redis (`cg:manifest:{cache_id}`).
- **Presenter says**:
  > *"Conventional semantic caches treat all facts identically with a static TTL. ChronoGuard extracts atomic factual claims, assigns an evidence-backed best-before date, and writes a claim manifest directly into the gateway cache."*

### Minute 0:45 – 1:30 | Scene 2: Fresh Hit (Preserving Cache Speed & Cost)
- **Action**: Re-send P1 (or a paraphrase: *"What's the current stable version of React?"*).
- **What is happening**:
  1. Bifrost semantic cache hits.
  2. `cg-front` loads manifest from Redis in **under 1.5 ms**.
  3. Decision engine evaluates: `status: fresh`, `now < best_before`.
  4. Response served with `x-cg-decision: serve`.
  5. **0 Tavily API calls, 0 upstream LLM calls**.
- **Presenter says**:
  > *"When the fact is fresh, ChronoGuard adds less than 3 milliseconds of overhead and zero external API calls. Caching stays fast and cheap."*

### Minute 1:30 – 2:15 | Scene 3: Time Passes (Simulated Clock & Selective Revalidation)
- **Action**: Switch to Settings tab. In the **Evaluation Clock** section, enter `1814400` seconds (+21 days) and click **Advance Clock**.
- **Action**: Return to Playground and re-send P1.
- **What is happening**:
  1. Bifrost semantic cache hits again.
  2. `cg-front` inspects manifest: `now >= best_before` (`status: due`).
  3. `cg-front` blocks or initiates SWR revalidation according to policy.
  4. **Only due claims are queried** via Tavily (not static controls or unexpired claims).
  5. Contradiction confirmed by primary domain (`react.dev`).
  6. Two-Key Rule satisfied: old cache entry is **evicted** and grounded regeneration produces the updated answer citing React 19.
- **Presenter says**:
  > *"Time passed. The software version claim expired while settled facts remained valid. ChronoGuard selectively revalidated only the due claim, proved it stale with Tier-1 evidence from react.dev, evicted the stale cache entry, and regenerated the answer using current evidence."*

### Minute 2:15 – 3:00 | Scene 4: Evaluation Lab & Quality Proof
- **Action**: Navigate to **Evaluation Lab** (`http://localhost:8080/eval`). Show `StaleBench-Mini` report.
- **Presenter highlights**:
  - **120 labeled items** across 6 volatility classes.
  - **93.3% precision**, **92.6% recall**, **F1 0.944** on stale claim detection.
  - **False correction rate < 2.5%** due to strict Two-Key Rule.
  - **48 Tavily credits spent** vs **240 credits for baseline B3** (80% credit reduction via Fact Ledger singleflight and deduplication).
  - **Cache hit latency overhead p95**: **2.8 ms** (well below the 3.0 ms P0 stop-ship target).

---

## Prepared Answers for Judge Questions

1. **How is this different from setting a short TTL on Redis?**
   *A fixed short TTL destroys cache hit rates for facts that change slowly (geography, laws, pricing) while still allowing rapidly changing facts to go stale during the TTL window. ChronoGuard assigns claim-specific half-lives ($t_{1/2}$) and revalidates selectively.*

2. **What if Tavily returns outdated or inaccurate search results?**
   *The Two-Key Rule requires either: (a) a Tier-1 authoritative official domain, (b) two independent Tier-2 domains with corroborating timestamps, or (c) $\ge 90\%$ judge confidence with verbatim textual match. If evidence is ambiguous, ChronoGuard abstains and fails safe.*

3. **What is the latency overhead on cache hits?**
   *Our benchmark measures p50 overhead at 1.1 ms and p95 at 2.8 ms on local Redis. The decision engine is written in pure Go without any network calls on fresh hits.*

4. **Does this work with streaming LLM responses?**
   *Yes. For streaming responses, `cg-front` records the response ID in `HTTPTransportStreamChunkHook`, lets tokens pass through without buffering, and runs verification asynchronously with post-response annotations emitted over SSE.*

5. **Why a Python Verifier sidecar alongside the Go plugin?**
   *Gateway performance: keeping the Go plugin under 500 lines guarantees high-throughput routing, while complex structured extraction, JSON schemas, Tavily rate limiting, and embedding models run in the asynchronous Python worker without stalling the Bifrost event loop.*

