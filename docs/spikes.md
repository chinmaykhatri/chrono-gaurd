# ChronoGuard Technical Spikes & Gateway Interoperability Report

> Documenting the 11 architectural assumptions and empirical findings for Bifrost gateway integration.

---

### Spike 1: Cache-Hit Metadata Fields
- **Finding:** Upstream Bifrost `plugins/semanticcache` populates `BifrostResponse.ExtraFields.CacheDebug` and headers.
- **Fields verified:**
  - `cached: true`
  - `cache_provider: "semanticcache"`
  - `similarity_score: float` (e.g. `0.94`)
  - `matched_prompt: string`
  - `original_request_id: string`
- **Reference:** `.upstream/bifrost/plugins/semanticcache/main.go:214-245`

### Spike 2: Cache Entry ID vs Request ID
- **Finding:** In Bifrost Semantic Cache, the cache entry storage key is indexed by the hash of the prompt and tenant identity. When returned on a cache hit, `original_request_id` reflects the ID of the request that originally populated the cache entry.
- **ChronoGuard handling:** ChronoGuard uses `original_request_id` (or fallback hash) as `cache_id` across manifests, Redis reverse index, and Verifier endpoints.

### Spike 3: Clear-By-ID Endpoint
- **Finding:** Bifrost does **not** expose a native `DELETE /api/cache-entries/{id}` public management route.
- **Fallback / Strategy:**
  - Direct Redis cache eviction: Invalidation deletes the corresponding key from Redis / vector store (`bf:cache:...`).
  - Metadata tombstoning: ChronoGuard marks `cg:tenant:manifest:{cache_id}` with status `evicted` or `stale`. Any subsequent semantic hit that loads this manifest immediately triggers `evict_regen` or `evict_lazy`.

### Spike 4: `x-bf-cache-ttl` Behavior
- **Finding:** Bifrost HTTP transport respects dynamic TTL configuration when passed via plugin config or context.
- **ChronoGuard handling:** `cg-front` sets dynamic per-class TTLs during `HTTPTransportPreHook` based on the prompt's classified volatility tier (e.g., 60s for `realtime`, 3600s for `news_events`, 86400s for `software_versions`, 30d for `static`).

### Spike 5: Async Cache Write Delay
- **Finding:** Bifrost Semantic Cache executes vector embedding and storage asynchronously in `PostLLMHook` to prevent adding latency to the client response stream.
- **Consequence:** Immediate back-to-back requests within 10ms may result in a cache miss if vector indexing is still in-flight.
- **Test Accommodation:** Gateway integration tests include a 50ms settling barrier when testing immediate cache hits.

### Spike 6: Caching of Short-Circuited Responses
- **Finding:** When a plugin short-circuits in `PreLLMHook` (`*schemas.LLMPluginShortCircuit`), subsequent plugins in the chain are skipped and the response is immediately returned.
- **Semantic Cache Behavior:** Semantic Cache's `PostLLMHook` is **not** called on short-circuited responses, meaning synthetic plugin responses are safely not cached as real model completions.

### Spike 7: Supported Vector Stores
- **Verified Stores:** Upstream Bifrost supports:
  1. `redis` (via RediSearch vector indexes)
  2. `weaviate` (verified with local container on port 9000)
  3. `chromem-go` (embedded in-memory pure Go store)
  4. `qdrant`
  5. `pinecone`
- **Default for ChronoGuard:** Redis + Weaviate.

### Spike 8: Plugin Order Semantics
- **Finding:**
  - Built-in placement order is strictly configured via `s.Config.SetPluginOrderInfo(name, placement, order)`.
  - **Pre-hooks** run in ascending order of registration:
    `cg-front` (6) -> `semanticcache` (7) -> `cg-back` (8) -> Provider.
  - **Post-hooks** run in reverse order:
    `cg-back` (8) -> `semanticcache` (7) -> `cg-front` (6).
- **Result:** `cg-front` sees both cache hits and cache misses on the return path, allowing unified decision engine evaluation.

### Spike 9: Context Propagation from HTTP Hooks to LLM Hooks
- **Finding:** Bifrost supplies `*schemas.BifrostContext` across all lifecycle stages (`HTTPTransportPreHook` -> `PreRequestHook` -> `PreLLMHook` -> `PostLLMHook`).
- **Implementation:** `chronoguard/bifrost/plugins/chronoguard/internal/runtime/context.go` stores `*runtime.State` under `runtime.StateKey`, guaranteeing policy, tenant, and classification state are preserved across all hooks without thread-local variables.

### Spike 10: Custom Keys in `ExtraFields`
- **Finding:** `BifrostResponse.ExtraFields` allows arbitrary custom properties.
- **Usage:** ChronoGuard safely propagates `x-cg-decision`, `x-cg-freshness-min`, and claim counts through both response headers and `ExtraFields` for downstream analytics.

### Spike 11: Metrics Exposure
- **Finding:** Upstream Bifrost exposes Prometheus metrics at `/metrics` through the `telemetry` plugin.
- **ChronoGuard metrics:** Verifier exposes Prometheus metrics (`cg_cache_hits_total`, `cg_stale_served_total`, `cg_claims_verified_total`, `cg_tavily_credits_used_total`, `cg_cascade_regens_total`) at `GET /metrics`.
