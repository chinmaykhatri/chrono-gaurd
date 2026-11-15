# ChronoGuard Architecture Specification

ChronoGuard is a freshness-aware reliability layer built for the **Bifrost AI Gateway** (by Maxim AI) and **Tavily AI**.

```
                +-------------------------------------------------------------+
                |                    Bifrost Gateway Core                     |
                |                                                             |
Request ------> |  [cg-front (Pre)]  -->  [semantic_cache]  -->  [cg-back]    | ------> Provider LLM
                |         |                       |                   |       |
                |         | (Hit / Miss State)    | (Cached Entry)    | (Grounding)
                |         v                       v                   v       |
Response <----- |  [cg-front (Post)] <--  [semantic_cache]  <--  [cg-back]    | <------ Provider Answer
                +-------------------------------------------------------------+
                               |                            ^
                  (Async Ingest / Verify)             (Regen Loopback)
                               v                            |
                +-------------------------------------------------------------+
                |                  ChronoGuard Verifier                       |
                |                                                             |
                |  - Volatility Classification   - Two-Key Evidence Judge     |
                |  - Tavily Search & Extract     - Grounded Prompt Synthesizer|
                |  - Freshness Calibration       - Cascade Invalidation       |
                +-------------------------------------------------------------+
                               |                            |
                               v                            v
                        [PostgreSQL 16]                 [Redis 7]
                        (Audit of Truth)            (Hot Path Cache)
```

---

## 1. Plugin Sandwich Pattern in Bifrost

Bifrost plugin hooks run **forward on the way in** and **in reverse on the way out**:

1. **`cg-front` Pre-Hook**:
   - Inspects caller headers (`x-cg-policy`, `x-cg-mode`).
   - Classifies user prompt into one of 8 volatility classes using zero-network token heuristics.
   - Sets `x-bf-cache-ttl` to the class hard TTL (e.g. 7 days for software versions, bypass for realtime).
   - Stamps request state (`request_id`, `policy`, `class`).

2. **`semantic_cache` (Bifrost Built-in)**:
   - Performs embedding lookup. If a vector match exceeds similarity threshold, marks cache hit.

3. **`cg-back` Pre-Hook**:
   - If `x-cg-ground-id` is present (from a ChronoGuard regeneration loop), loads evidence from Redis and prepends a system instruction grounding the model in verified reality.

4. **Model Provider**:
   - Executes completion if cache missed.

5. **`cg-back` Post-Hook**:
   - Tags origin (`provider` vs `regenerated`). Runs before `semantic_cache` writes the entry.

6. **`cg-front` Post-Hook**:
   - Runs **last** on the way out:
     - **On Cache Hit**: Loads manifest from Redis (`cg:manifest:{cache_id}`). If `now < best_before`, immediately serves (`p95 < 2.8 ms`). If expired, triggers revalidation or regeneration according to policy.
     - **On Cache Miss**: Initiates synchronous inline verification (under `strict` policy) or non-blocking asynchronous ingestion (`standard`/`lenient`).

---

## 2. Redis Hot-Path Namespace

| Key Pattern | Data Structure | TTL | Purpose |
|---|---|---|---|
| `cg:manifest:{cache_id}` | JSON string | Hard Expiry + 1d | Claim manifest with claim list, statuses, and `best_before` |
| `cg:fact:{fact_hash}` | Hash | Variable | Fact ledger: `current_value`, `last_verdict`, `fresh_until` |
| `cg:sf:{fact_hash}` | String (Token) | 30s | Singleflight lock to deduplicate concurrent verifications |
| `cg:rv:{fact_hash}` | String | 60s | Revalidation deduplication flag |
| `cg:ground:{ground_id}` | JSON string | 600s | Grounding bundle passed to `cg-back` during regeneration |
| `cg:clock` | Hash | Persistent | Simulated clock state (`mode`, `offset_seconds`, `frozen_at`) |
| `cg:events` | Pub/Sub | N/A | Real-time event notifications delivered to React Console SSE |

---

## 3. Freshness Scoring Formula

For claim $i$ with category half-life $t_{1/2}$ and evidence $E$:

$$z = -1.0 + \beta_{\text{verdict}} + 1.5 \cdot \alpha_{\text{auth}} + 0.8 \cdot \rho_{\text{recency}} + 0.8 \cdot \gamma_{\text{agree}} - 2.0 \cdot \chi_{\text{contra}} + 0.4 \cdot \text{logit}(1 - p_{\text{stale}})$$

Where:
- $\beta_{\text{verdict}} \in \{+2.5\text{ (confirmed)}, -2.0\text{ (outdated)}, -2.5\text{ (contradicted)}\}$
- $\alpha_{\text{auth}} = \max_{e \in E_{\text{support}}} \text{TierWeight}(e) \in \{1.0, 0.7, 0.4, 0.2\}$
- $\rho_{\text{recency}} = 2^{-\Delta t / t_{1/2}}$ based on published date of evidence
- $\text{Freshness} = \frac{100}{1 + e^{-z}} \in [0, 100]$

---

## 4. The Two-Key Evidence Rule

A cache entry is **never evicted** and text is **never rewritten** unless contradictory evidence meets at least one of three non-negotiable criteria:
1. **Tier 1 Official Contradiction**: Direct contradiction from the entity's official documentation or primary registry domain.
2. **Dual-Source Tier 2 Corroboration**: Contradiction confirmed by at least two distinct independent Tier 2 domains.
3. **High-Confidence Verbatim Match**: Judge model confidence $\ge 90\%$ where the corrected value appears verbatim in an authoritative snippet.

