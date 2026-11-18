# Verification and release gates

The Document 05 gates are evaluated against observed executions. Tests using fake models and scripted evidence are labeled simulation; they do not establish live retrieval quality.

| Boundary | Required checks | Type |
| --- | --- | --- |
| Gateway lifecycle | Actual plugin order, hit metadata, cache identity, exact eviction, next request miss | Real Bifrost integration |
| Cache decisions | Fresh hit makes no upstream/Tavily call; due-only verification; strict never serves stale/pending uncertainty | Go unit and integration |
| Verification | Atomic extraction, schema failures, private claims skipped, evidence references validated, conservative abstention | Python unit/contract |
| Shared state | Concurrent identical facts share work; different tenants/values cannot reuse incorrect verdicts; CAS preserves stale updates | Redis/Postgres integration |
| Failure containment | Dependency timeout, cancellation, exhausted budgets, lost worker, unavailable manifest, failed regeneration | Fault injection |
| Security | Spoofed internal headers, CSRF, brute-force rate caps, tenant isolation, malicious URLs, untrusted text, secret redaction | Adversarial API/integration |
| Console | Login/session expiry; API errors; real empty states; navigation; mutation rollback; safe source links | Type checks, component and browser tests |
| Persistence | Fresh database migrations, restart, retention, reconciliation, backup/restore | Database integration |
| Quality | Entity-separated reviewed labels, confusion counts, abstention, false corrections, citation validity, calibration | Versioned evaluation |
| Performance | Warm repeated baseline and enabled runs, identical hardware/load, p50/p95/p99 and raw counts | Actual gateway benchmark |
| Deployment | Locked dependencies, image builds, health checks, private internal ports, non-root app containers | Compose/CI |

Release stops on known-stale strict responses, hot-path panics, secret disclosure, failing end-to-end loops, or unverified integration assumptions. Dataset human review and live accuracy remain explicit gates; synthetic fixtures cannot satisfy them.
