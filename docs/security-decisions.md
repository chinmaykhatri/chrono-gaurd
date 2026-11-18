# Security decisions and review scope

The system processes untrusted prompts, model output and web evidence. These inputs are data; they cannot grant access, select arbitrary network destinations, or alter source authority policy.

## Trust boundaries

The console receives an HttpOnly session cookie and a CSRF token, never provider credentials. The verifier's internal API requires an independent constant-time checked secret. The gateway authenticates internal traffic before honoring control headers. Production ingress must not expose gateway administration, database ports, Redis ports or internal verifier routes.

Tenant identifiers come from authenticated configuration/governance, not arbitrary user headers. Fact keys, manifests, locks, idempotency and cache namespaces must include the tenant. A shared fact's verified value must be compared with each new claim's stated value; a fact identity alone cannot establish a claim's truth.

## Failure and freshness

Strict responses with unresolved material claims are withheld when policy requires fail-closed. Neither stale streaming tokens nor fallback stale text can be labeled fresh. Missing manifests, failed persistence and revision conflicts never imply verification. Known stale entries remain stale when eviction or regeneration fails.

## Secrets and deployment

Ignored local `.env` and `.admin-password` hold development secrets. The bootstrap generates random keys and an Argon2id password hash without logging their values. Production requires TLS, deployment-specific secrets and a restrictive origin. Containers should have minimal permissions and private service networks; only the intended frontend and inference ingress are published.

Version pins and lockfiles make builds reproducible. Dependency scans and container scans are release evidence, not substitutes for authentication, isolation, concurrency and failure tests. The Docker engine is a trusted administrative boundary.

## Review status

Implementation is in progress. These are required invariants, not a claim that a security audit is complete. The independent security role will report code findings and tests in the implementation status document.
