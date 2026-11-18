# Feature A: Shadow Mode and ROI Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement shadow policy mode (flag `shadow.enabled` or header `x-cg-shadow: 1`) where ChronoGuard evaluates decisions without altering responses (byte-identical passthrough), records `decision_shadow`, and serves a dedicated `/roi` console page with real & projected metrics.

**Architecture:**
- **Go Bifrost Plugin (`front/plugin.go`):** Reads `x-cg-shadow` header or `ShadowEnabled` config. Runs decision engine normally. Sets `s.Shadow = true`, `s.ShadowDecision = d`, `s.Decision = "passthrough"`, passes through original bytes with `x-cg-shadow: 1` and `x-cg-decision-shadow: <decision>` headers. Dispatches background revalidation without cache eviction.
- **Python Verifier (`app/main.py`, `app/db.py`, `app/repository.py`):** Adds `shadow_enabled: bool = False` to `Settings`. Migrates `requests` table with `decision_shadow` and `shadow_reason` columns. Exposes `/internal/v1/record-hit` and `/api/v1/roi` endpoints.
- **Console (`App.tsx`, `pages/ROI.tsx`):** Adds top-level `/roi` route, sidebar navigation, metric cards (requests observed, hit rate, stale served in shadow, entries at risk), top stale facts table, cost vs savings (LIVE/SIMULATED), recommendation card, and Export JSON / Copy Markdown actions.
- **Automated Verification:** Comprehensive test suite in `chronoguard/verifier/tests/test_shadow.py` and evaluation report in `chronoguard/eval/reports/roi-shadow-<timestamp>.json`.

**Tech Stack:** Go 1.23+, Python FastAPI / SQLAlchemy / asyncpg, TypeScript / React 19 / Vite.

---

### Task 1: Database Migration & Configuration Flag

**Files:**
- Modify: `chronoguard/verifier/app/config.py`
- Modify: `chronoguard/verifier/app/db.py`
- Modify: `chronoguard/verifier/app/repository.py`

- [ ] **Step 1: Add `shadow_enabled` to Settings**
In `chronoguard/verifier/app/config.py`, add `shadow_enabled: bool = Field(False)` to `Settings`.

- [ ] **Step 2: Add `decision_shadow` and `shadow_reason` to requests table**
In `chronoguard/verifier/app/db.py`, add:
```python
sa.Column("decision_shadow", sa.String(32)), sa.Column("shadow_reason", sa.Text),
```
to `requests` table.

- [ ] **Step 3: Update `Repository.seed()` with idempotent column addition**
In `chronoguard/verifier/app/repository.py`, add idempotent `ALTER TABLE requests ADD COLUMN IF NOT EXISTS ...` in `seed()` so existing databases get upgraded automatically.

- [ ] **Step 4: Update `Repository.ingest()` and create `Repository.record_hit()`**
In `chronoguard/verifier/app/repository.py`, save `decision_shadow` and `shadow_reason` when present in `Ingest` and add `record_hit(...)` method for tracking cache hits.

- [ ] **Step 5: Verify with existing pytest**
Run `uv run pytest -q` in `chronoguard/verifier` to ensure no schema regressions.

---

### Task 2: Verifier API Contracts & Endpoints (`/internal/v1/record-hit` & `/api/v1/roi`)

**Files:**
- Modify: `chronoguard/verifier/app/schemas/contracts.py`
- Modify: `chronoguard/verifier/app/main.py`

- [ ] **Step 1: Update contracts for shadow tracking**
In `chronoguard/verifier/app/schemas/contracts.py`, add `decision_shadow` and `shadow_reason` to `Ingest` and define `RecordHit` schema.

- [ ] **Step 2: Add `/internal/v1/record-hit` endpoint**
In `chronoguard/verifier/app/main.py`, implement `/internal/v1/record-hit` with `require_internal` auth, creating a request record with `cache_status="hit"` and recording shadow metrics.

- [ ] **Step 3: Add `/api/v1/roi` endpoint**
In `chronoguard/verifier/app/main.py`, implement `/api/v1/roi` with window filter (`1h`, `24h`, `7d`), computing:
- `requests_observed`
- `hit_rate`
- `stale_would_have_served` (shadow decisions `evict_regen`, `evict_lazy`, `fail_closed`)
- `entries_at_risk`
- `top_stale_facts`
- `verification_cost` (labeled LIVE)
- `projected_savings` (labeled SIMULATED)
- `recommendation` (rule-based algorithmic summary)

- [ ] **Step 4: Update Playground chat to support shadow mode**
In `playground_chat`, check for `x-cg-shadow` header or `settings.shadow_enabled` and record shadow metrics accordingly.

---

### Task 3: Bifrost Go Plugin Shadow Mode

**Files:**
- Modify: `chronoguard/bifrost/plugins/chronoguard/internal/runtime/runtime.go`
- Modify: `chronoguard/bifrost/plugins/chronoguard/front/plugin.go`
- Modify: `chronoguard/bifrost/plugins/chronoguard/front/plugin_test.go`

- [ ] **Step 1: Update `runtime.Config` and `runtime.State`**
Add `ShadowEnabled bool` to `runtime.Config` and `Shadow bool`, `ShadowDecision string`, `ShadowReason string` to `runtime.State`.

- [ ] **Step 2: Update `front/plugin.go`**
In `HTTPTransportPreHook`, detect `x-cg-shadow` header or config. In `handleHit`, when `s.Shadow` is true, evaluate `d := decide.Decide(m, s.Policy, now)`, record `s.ShadowDecision`, set `s.Decision = "passthrough"`, dispatch background revalidation without cache eviction, and return the untouched cached response.
In `HTTPTransportResponseHeadersHook`, attach `x-cg-shadow: 1` and `x-cg-decision-shadow: <decision>`.

- [ ] **Step 3: Add unit tests in `front/plugin_test.go`**
Test shadow mode headers, passthrough behavior, and decision preservation.

- [ ] **Step 4: Run `go test ./...`**
Verify all Go packages pass cleanly.

---

### Task 4: Console `/roi` Page & Navigation

**Files:**
- Create: `chronoguard/console/src/pages/ROI.tsx`
- Modify: `chronoguard/console/src/App.tsx`

- [ ] **Step 1: Create `ROI.tsx` component**
Build the ROI dashboard with:
- Window selector (1h, 24h, 7d)
- Metric cards: Requests Observed, Hit Rate, Stale Answers Prevented / At Risk, Net Projected Value
- Top Stale Facts table with diff columns
- Verification Cost (LIVE) vs Projected Savings (SIMULATED) breakdown
- Dynamic recommendation box
- "Export JSON" button & "Copy Markdown report" button

- [ ] **Step 2: Integrate `/roi` into `App.tsx`**
Add `['/roi', 'ROI report']` to navigation links and register `<Route path="/roi" element={<ROI revision={events.revision}/>}/>`.

- [ ] **Step 3: Run console build**
Run `npm run build` in `chronoguard/console` and ensure 0 TypeScript or Vite errors.

---

### Task 5: Automated Testing & Evaluation Report

**Files:**
- Create: `chronoguard/verifier/tests/test_shadow.py`
- Create: `chronoguard/eval/reports/roi-shadow-verified.json`

- [ ] **Step 1: Write `test_shadow.py`**
Cover:
1. Passthrough response is byte-identical with shadow enabled
2. Cache is not evicted when stale entry is hit under shadow mode
3. Request records contain `decision_shadow` and `shadow_reason`
4. `/api/v1/roi` accurately counts `stale_would_have_served` and generates correct recommendation

- [ ] **Step 2: Run pytest**
Ensure all tests (34 existing + new shadow tests) pass.

- [ ] **Step 3: Run full `verify-proof` Gate G1**
Ensure all 10 checks pass.

- [ ] **Step 4: Commit**
`WP-A: shadow mode and ROI report`
