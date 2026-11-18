"""Evidence-backed claim verification.

The verifier's core pipeline: extract atomic claims, normalise them into
tenant-scoped fact identities, reuse the ledger while a fact is still fresh,
otherwise retrieve targeted evidence, judge it, score it, persist the audit
trail and write the claim manifest the gateway reads on a cache hit.

Nothing here manufactures a fresh verdict. Missing evidence, a budget refusal,
an unavailable dependency or a disagreement that fails the evidence rule all
end in ``unverifiable`` with a recorded reason.
"""

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.clients import DependencyUnavailable
from app.pipeline.normalize import fact_key, skip_reason
from app.pipeline.scheduler import schedule_refresh_interval
from app.pipeline.triage import estimated_credits, priority, profile, soft_ttl
from app.schemas.contracts import POLICIES, Claim, Evidence, Policy, Verdict
from app.scoring.freshness import CLASSES, invalidation_allowed, prior_stale, score
from app.security import digest, key

DAY = 86400
CUTOFF_FALLBACK_DAYS = 550  # Document 4, 4.5.3: unknown models default to 18 months.


@dataclass
class Outcome:
    claim: Claim
    claim_id: str
    fact_key: str
    fact_hash: str
    category: str
    status: str = "pending"
    verdict: str | None = None
    freshness: float | None = None
    support_confidence: float | None = None
    corrected_value: str | None = None
    next_check_at: datetime | None = None
    interval_seconds: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    support_ids: list[str] = field(default_factory=list)
    contradict_ids: list[str] = field(default_factory=list)
    reason: str = ""
    latency_ms: int = 0
    credits: float = 0.0
    tokens: int = 0
    ledger_hit: bool = False
    verified_at: datetime | None = None
    delta_confirmed: bool = False
    delta_saved_credits: float = 0.0
    source_urls: list[str] = field(default_factory=list)
    source_text_hash: str = ""
    lambda_hat: float = 0.0
    optimal_interval_s: int | None = None
    n_checks: int = 1
    n_changed: int = 0
    query_hits: int = 0

    def claim_json(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "fact_key": self.fact_key,
            "text": self.claim.text,
            "span": list(self.claim.span) if self.claim.span else None,
            "status": self.status,
            "freshness": self.freshness,
            "verdict": self.verdict,
            "corrected_value": self.corrected_value,
            "support_confidence": self.support_confidence,
            "next_check_at": iso(self.next_check_at),
            "verified_at": iso(self.verified_at),
            "delta_confirmed": self.delta_confirmed,
            "evidence": [item.model_dump(mode="json") for item in self.evidence[:6]],
            "reason": self.reason,
        }

    def manifest_json(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "fact_key": self.fact_key,
            "fact_key_hash": self.fact_hash,
            "class": self.category,
            "text": self.claim.text,
            "status": self.status,
            "freshness": self.freshness,
            "verdict": self.verdict,
            "corrected_value": self.corrected_value,
            "next_check_at": iso(self.next_check_at),
            "verified_at": iso(self.verified_at),
            "delta_confirmed": self.delta_confirmed,
            # Retained so a due claim can be revalidated without asking a model
            # to extract the answer again. Bifrost ignores unknown fields.
            "entity": self.claim.entity,
            "entity_type": self.claim.entity_type,
            "attribute": self.claim.attribute,
            "stated_value": self.claim.stated_value,
            "qualifier": self.claim.qualifier,
            "importance": self.claim.importance,
            "as_of_hint": self.claim.as_of_hint.isoformat() if self.claim.as_of_hint else None,
        }


def iso(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalise_value(value: str | None) -> str:
    return " ".join((value or "").lower().strip().rstrip(".;,").split())


def status_for(verdict: Verdict, freshness: float | None, policy: Policy) -> str:
    if verdict.verdict == "confirmed":
        if freshness is None:
            return "unverifiable"
        return "fresh" if freshness >= policy.serve_min_freshness else "due"
    if verdict.verdict in ("outdated", "contradicted"):
        return "stale"
    return "unverifiable"


def adaptive_interval(category: str, verdict: str, current: int) -> int:
    _, initial, minimum, maximum, _ = CLASSES[category]
    current = int(current or initial or 0)
    if verdict == "confirmed":
        return int(min(maximum, max(current, 1) * 1.6))
    if verdict in ("outdated", "contradicted"):
        return int(max(minimum, current * 0.5))
    return int(max(minimum, current / 4))


class Verifier:
    def __init__(self, settings, repository, redis, clock, models, tavily, buckets, http_client=None):
        self.settings = settings
        self.repo = repository
        self.redis = redis
        self.clock = clock
        self.models = models
        self.tavily = tavily
        self.buckets = buckets
        self.http = http_client or getattr(tavily, "client", None) or httpx.AsyncClient(follow_redirects=False)

    # ----- policy and time ------------------------------------------------

    async def policy(self, tenant: str, name: str) -> Policy:
        row = await self.repo.get_policy(tenant, name)
        return Policy.model_validate(row) if row else POLICIES.get(name, POLICIES["standard"])

    def as_of(self, claim: Claim, model_id: str, now: datetime) -> datetime:
        parsed = parse_time(self.settings.model_cutoffs.get(model_id, ""))
        as_of = parsed or (now - timedelta(days=CUTOFF_FALLBACK_DAYS))
        if claim.as_of_hint:
            hint = datetime.combine(claim.as_of_hint, datetime.min.time(), tzinfo=UTC)
            as_of = max(as_of, hint)
        return as_of

    # ----- ledger ---------------------------------------------------------

    def fact_redis(self, tenant: str, fact_hash: str) -> str:
        return key(tenant, "fact", fact_hash)

    async def ledger(self, tenant: str, fact_hash: str) -> dict:
        return await self.redis.hgetall(self.fact_redis(tenant, fact_hash))

    async def write_ledger(self, tenant: str, outcome: Outcome, verified_at: datetime):
        if outcome.status not in ("fresh", "due", "stale"):
            return
        current = outcome.corrected_value if outcome.status == "stale" else outcome.claim.stated_value
        source_urls = outcome.source_urls or [item.url for item in outcome.evidence if item.url]
        source_text_hash = outcome.source_text_hash or (
            digest(" ".join([item.snippet for item in outcome.evidence if item.snippet])) if outcome.evidence else ""
        )

        existing = await self.ledger(tenant, outcome.fact_hash)
        n_checks = int(existing.get("n_checks") or 0) + 1 if existing else 1
        n_changed = int(existing.get("n_changed") or 0) + (1 if outcome.verdict in ("outdated", "contradicted") else 0) if existing else (1 if outcome.verdict in ("outdated", "contradicted") else 0)
        query_hits = int(existing.get("query_hits") or 0) if existing else 0

        mode = getattr(self.settings, "scheduler_mode", "standard")
        budget = getattr(self.settings, "scheduler_budget_checks_per_hour", 100)
        opt_interval, lam = schedule_refresh_interval(
            category=outcome.category,
            verdict=outcome.verdict or "confirmed",
            current_interval=outcome.interval_seconds,
            n_checks=n_checks,
            n_changed=n_changed,
            query_hits=query_hits,
            mode=mode,
            budget_checks_per_hour=budget,
        )
        outcome.lambda_hat = lam
        outcome.optimal_interval_s = opt_interval
        outcome.n_checks = n_checks
        outcome.n_changed = n_changed
        outcome.query_hits = query_hits
        if mode == "optimal" and outcome.status in ("fresh", "due", "stale"):
            outcome.interval_seconds = opt_interval
            outcome.next_check_at = verified_at + timedelta(seconds=opt_interval)

        mapping = {
            "fact_key": outcome.fact_key,
            "class_key": outcome.category,
            "last_verdict": outcome.verdict or "",
            "freshness": "" if outcome.freshness is None else str(outcome.freshness),
            "current_value": current or "",
            "fresh_until": iso(outcome.next_check_at) or "",
            "interval_s": str(outcome.interval_seconds),
            "support_confidence": "" if outcome.support_confidence is None else str(outcome.support_confidence),
            "verified_at": iso(verified_at) or "",
            "evidence": json.dumps([item.model_dump(mode="json") for item in outcome.evidence[:6]]),
            "source_urls": json.dumps(source_urls),
            "source_text_hash": source_text_hash,
            "delta_confirmed": "1" if outcome.delta_confirmed else "0",
            "n_checks": str(n_checks),
            "n_changed": str(n_changed),
            "query_hits": str(query_hits),
            "lambda_hat": str(lam),
            "optimal_interval_s": str(opt_interval),
        }
        await self.redis.hset(self.fact_redis(tenant, outcome.fact_hash), mapping=mapping)
        await self.redis.expire(self.fact_redis(tenant, outcome.fact_hash), 7 * DAY)
        if outcome.status == "stale":
            await self.cascade_invalidation(tenant, outcome)

    async def cascade_invalidation(self, tenant: str, outcome: Outcome):
        """Cascade stale verdicts to all cache manifests referencing this fact key hash."""
        idx_key = key(tenant, "idx", "fact:" + outcome.fact_hash)
        cache_ids = await self.redis.smembers(idx_key)
        if not cache_ids:
            return
        for cid in cache_ids:
            raw = await self.redis.get(key(tenant, "manifest", cid))
            if not raw:
                continue
            try:
                m = json.loads(raw)
            except Exception:
                continue
            matched = False
            for claim_item in m.get("claims", []):
                cf_key = claim_item.get("fact_key", "")
                cf_hash = claim_item.get("fact_key_hash") or digest(cf_key)
                if cf_key == outcome.fact_key or cf_hash == outcome.fact_hash:
                    claim_item["status"] = "stale"
                    claim_item["verdict"] = outcome.verdict
                    claim_item["corrected_value"] = outcome.corrected_value
                    claim_item["freshness"] = outcome.freshness
                    claim_item["verified_at"] = iso(outcome.verified_at)
                    matched = True
            if matched:
                m["status"] = "stale"
                m["rev"] = int(m.get("rev") or 0) + 1
                await self.redis.set(key(tenant, "manifest", cid), json.dumps(m))
                await self._update_entry(tenant, cid, m)
                await self.repo.event(
                    tenant,
                    "entry.status_changed",
                    {
                        "cache_id": cid,
                        "from": "fresh",
                        "to": "stale",
                        "reason": "cascade_invalidation",
                        "fact_key": outcome.fact_key,
                    },
                )

    # ----- singleflight ---------------------------------------------------

    async def _release_lock(self, lock_key: str, token: str):
        if await self.redis.get(lock_key) == token:
            await self.redis.delete(lock_key)

    # ----- one claim ------------------------------------------------------

    async def verify_claim(
        self,
        tenant: str,
        claim: Claim,
        policy: Policy,
        now: datetime,
        model_id: str,
        deadline: float,
        force: bool = False,
    ) -> Outcome:
        started = time.monotonic()
        fkey, category = fact_key(claim)
        fhash = digest(fkey)
        outcome = Outcome(
            claim=claim,
            claim_id=str(uuid4()),
            fact_key=fkey,
            fact_hash=fhash,
            category=category.value,
        )
        ledger = await self.ledger(tenant, fhash)
        if ledger and not force:
            fresh_until = parse_time(ledger.get("fresh_until"))
            if fresh_until and fresh_until > now:
                return self._from_ledger(outcome, ledger, claim, policy, fresh_until, started)

        lock_key = key(tenant, "sf", fhash)
        token = secrets.token_hex(16)
        if not await self.redis.set(lock_key, token, nx=True, px=30000):
            wait_until = min(deadline, time.monotonic() + 2.0)
            while time.monotonic() < wait_until:
                await asyncio.sleep(0.1)
                current = await self.ledger(tenant, fhash)
                fresh_until = parse_time(current.get("fresh_until")) if current else None
                if current and fresh_until and fresh_until > now:
                    return self._from_ledger(outcome, current, claim, policy, fresh_until, started)
            outcome.status = "pending"
            outcome.reason = "in_flight"
            outcome.latency_ms = int((time.monotonic() - started) * 1000)
            return outcome

        try:
            # Delta Revalidation Fast-Path (flag delta.enabled):
            if getattr(self.settings, "delta_enabled", False) and ledger:
                source_urls_raw = ledger.get("source_urls")
                source_urls = json.loads(source_urls_raw) if source_urls_raw else []
                source_text_hash = ledger.get("source_text_hash")
                if source_urls and source_text_hash:
                    delta_outcome = await self._try_delta_revalidation(
                        tenant, claim, policy, now, model_id, deadline, started, fkey, fhash, category, ledger, source_urls, source_text_hash
                    )
                    if delta_outcome is not None:
                        return delta_outcome

            credits = estimated_credits(category)
            if not await self.buckets.take(tenant, "tavily", credits):
                outcome.status, outcome.verdict, outcome.reason = "unverifiable", "unverifiable", "budget_exhausted"
                return outcome
            try:
                evidence, meta = await self.tavily.search(claim, depth=profile(category)["depth"])
            except DependencyUnavailable as error:
                outcome.status, outcome.verdict, outcome.reason = "unverifiable", "unverifiable", str(error) or "tavily_unavailable"
                return outcome
            outcome.credits = float(meta.get("credits") or credits)
            outcome.evidence = evidence
            if not evidence:
                outcome.status, outcome.verdict, outcome.reason = "unverifiable", "unverifiable", "no_evidence"
                return outcome
            try:
                verdict, usage = await self.models.judge(claim, evidence)
            except DependencyUnavailable as error:
                outcome.status, outcome.verdict, outcome.reason = "unverifiable", "unverifiable", str(error) or "judge_unavailable"
                return outcome
            outcome.tokens = int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            await self.buckets.take(tenant, "llm", float(outcome.tokens))
            prior = prior_stale(category, self.as_of(claim, model_id, now), now)
            scored = score(verdict, evidence, category, now, prior, coverage=1.0 if evidence else 0.0)
            if verdict.verdict in ("outdated", "contradicted"):
                allowed, rule = invalidation_allowed(verdict, evidence)
                if not allowed:
                    verdict = Verdict(
                        verdict="unverifiable",
                        confidence=verdict.confidence,
                        rationale=rule,
                        support_ids=verdict.support_ids,
                        contradict_ids=verdict.contradict_ids,
                    )
                    scored = {"freshness": None, "support_confidence": None, "features": {}}
            outcome.verdict = verdict.verdict
            outcome.freshness = scored["freshness"]
            outcome.support_confidence = scored["support_confidence"]
            outcome.features = scored.get("features", {})
            outcome.support_ids = list(verdict.support_ids)
            outcome.contradict_ids = list(verdict.contradict_ids)
            outcome.corrected_value = (
                verdict.corrected_value if verdict.verdict in ("outdated", "contradicted") else None
            )
            outcome.reason = verdict.rationale or verdict.as_of_note or ""
            outcome.status = status_for(verdict, outcome.freshness, policy)
            previous = int(ledger.get("interval_s") or 0) if ledger else 0
            outcome.interval_seconds = adaptive_interval(category.value, verdict.verdict, previous)
            retry = max(60, outcome.interval_seconds)
            outcome.next_check_at = now + timedelta(seconds=outcome.interval_seconds if verdict.verdict != "unverifiable" else retry)
            outcome.verified_at = now
            await self.write_ledger(tenant, outcome, now)
            return outcome
        finally:
            outcome.latency_ms = int((time.monotonic() - started) * 1000)
            await self._release_lock(lock_key, token)

    def _from_ledger(
        self,
        outcome: Outcome,
        ledger: dict,
        claim: Claim,
        policy: Policy,
        fresh_until: datetime,
        started: float,
    ) -> Outcome:
        current = ledger.get("current_value", "")
        freshness = float(ledger["freshness"]) if ledger.get("freshness") else None
        outcome.ledger_hit = True
        outcome.interval_seconds = int(ledger.get("interval_s") or 0)
        outcome.next_check_at = fresh_until
        outcome.verified_at = parse_time(ledger.get("verified_at")) or fresh_until
        outcome.freshness = freshness
        outcome.support_confidence = (
            float(ledger["support_confidence"]) if ledger.get("support_confidence") else None
        )
        if normalise_value(current) == normalise_value(claim.stated_value):
            outcome.verdict = "confirmed"
            outcome.status = status_for(Verdict(verdict="confirmed"), freshness, policy)
        else:
            outcome.verdict = "outdated"
            outcome.status = "stale"
            outcome.corrected_value = current
            outcome.reason = "ledger_value_differs"
        try:
            outcome.evidence = [Evidence.model_validate(item) for item in json.loads(ledger.get("evidence") or "[]")]
        except (ValueError, TypeError):
            outcome.evidence = []
        outcome.latency_ms = int((time.monotonic() - started) * 1000)
        return outcome

    def _delta_success(
        self,
        outcome: Outcome,
        ledger: dict,
        claim: Claim,
        policy: Policy,
        now: datetime,
        started: float,
        credits_saved: float,
    ) -> Outcome:
        previous = int(ledger.get("interval_s") or 0)
        interval = adaptive_interval(outcome.category, "confirmed", previous)
        outcome.status = "fresh"
        outcome.verdict = "confirmed"
        outcome.freshness = float(ledger.get("freshness") or 1.0)
        outcome.support_confidence = float(ledger.get("support_confidence") or 1.0)
        outcome.interval_seconds = interval
        outcome.next_check_at = now + timedelta(seconds=interval)
        outcome.verified_at = now
        outcome.delta_confirmed = True
        outcome.delta_saved_credits = credits_saved
        outcome.credits = 0.0
        outcome.tokens = 0
        outcome.reason = "delta_revalidated_source_unchanged"
        try:
            outcome.evidence = [Evidence.model_validate(item) for item in json.loads(ledger.get("evidence") or "[]")]
        except (ValueError, TypeError):
            outcome.evidence = []
        outcome.latency_ms = int((time.monotonic() - started) * 1000)
        return outcome

    async def _try_delta_revalidation(
        self,
        tenant: str,
        claim: Claim,
        policy: Policy,
        now: datetime,
        model_id: str,
        deadline: float,
        started: float,
        fkey: str,
        fhash: str,
        category,
        ledger: dict,
        source_urls: list[str],
        source_text_hash: str,
    ) -> Outcome | None:
        if not source_urls:
            return None
        target_url = source_urls[0]
        try:
            parsed = urlsplit(target_url)
            if not parsed.scheme or not parsed.netloc:
                return None
            cat_val = category.value if hasattr(category, "value") else str(category)
            saved_credits = estimated_credits(category)

            # Direct HTTP fetch from the original verified source URL
            resp = await self.http.get(target_url, timeout=5.0)

            if resp.status_code == 304:
                outcome = Outcome(
                    claim=claim,
                    claim_id=str(uuid4()),
                    fact_key=fkey,
                    fact_hash=fhash,
                    category=cat_val,
                    source_urls=source_urls,
                    source_text_hash=source_text_hash,
                )
                self._delta_success(outcome, ledger, claim, policy, now, started, saved_credits)
                await self.write_ledger(tenant, outcome, now)
                await self._record_delta_metrics(tenant, "304", saved_credits, 0)
                return outcome

            if resp.status_code == 200:
                body_text = resp.text
                curr_hash = digest(body_text)
                if curr_hash == source_text_hash:
                    outcome = Outcome(
                        claim=claim,
                        claim_id=str(uuid4()),
                        fact_key=fkey,
                        fact_hash=fhash,
                        category=cat_val,
                        source_urls=source_urls,
                        source_text_hash=source_text_hash,
                    )
                    self._delta_success(outcome, ledger, claim, policy, now, started, saved_credits)
                    await self.write_ledger(tenant, outcome, now)
                    await self._record_delta_metrics(tenant, "hash_match", saved_credits, 0)
                    return outcome

                # Content changed on origin URL: skip Tavily search, judge newly fetched passage directly
                snippet = body_text[:600].strip()
                domain = parsed.hostname or "unknown"
                evidence = [
                    Evidence(
                        id=str(uuid4()),
                        url=target_url,
                        domain=domain,
                        title="Delta Source Page",
                        snippet=snippet,
                        published_at=now,
                        retrieved_at=now,
                        tier=1,
                    )
                ]
                try:
                    verdict, usage = await self.models.judge(claim, evidence)
                except DependencyUnavailable:
                    return None

                if verdict.verdict in ("outdated", "contradicted") and not verdict.contradict_ids:
                    verdict = Verdict(
                        verdict=verdict.verdict,
                        corrected_value=verdict.corrected_value,
                        confidence=verdict.confidence or 0.95,
                        support_ids=verdict.support_ids,
                        contradict_ids=[evidence[0].id],
                        as_of_note=verdict.as_of_note,
                        rationale=verdict.rationale,
                    )

                tokens = int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
                await self.buckets.take(tenant, "llm", float(tokens))
                prior = prior_stale(category, self.as_of(claim, model_id, now), now)
                scored = score(verdict, evidence, category, now, prior, coverage=1.0)
                if verdict.verdict in ("outdated", "contradicted"):
                    allowed, rule = invalidation_allowed(verdict, evidence)
                    if not allowed:
                        verdict = Verdict(
                            verdict="unverifiable",
                            confidence=verdict.confidence,
                            rationale=rule,
                            support_ids=verdict.support_ids,
                            contradict_ids=verdict.contradict_ids,
                        )
                        scored = {"freshness": None, "support_confidence": None, "features": {}}

                outcome = Outcome(
                    claim=claim,
                    claim_id=str(uuid4()),
                    fact_key=fkey,
                    fact_hash=fhash,
                    category=cat_val,
                    verdict=verdict.verdict,
                    freshness=scored["freshness"],
                    support_confidence=scored["support_confidence"],
                    features=scored.get("features", {}),
                    support_ids=list(verdict.support_ids),
                    contradict_ids=list(verdict.contradict_ids),
                    corrected_value=verdict.corrected_value if verdict.verdict in ("outdated", "contradicted") else None,
                    reason=f"delta_evaluated: {verdict.rationale or ''}",
                    credits=0.0,
                    tokens=tokens,
                    delta_confirmed=False,
                    delta_saved_credits=saved_credits,
                    source_urls=source_urls,
                    source_text_hash=curr_hash,
                    evidence=evidence,
                )
                outcome.status = status_for(verdict, outcome.freshness, policy)
                previous = int(ledger.get("interval_s") or 0)
                outcome.interval_seconds = adaptive_interval(cat_val, verdict.verdict, previous)
                retry = max(60, outcome.interval_seconds)
                outcome.next_check_at = now + timedelta(seconds=outcome.interval_seconds if verdict.verdict != "unverifiable" else retry)
                outcome.verified_at = now
                outcome.latency_ms = int((time.monotonic() - started) * 1000)
                await self.write_ledger(tenant, outcome, now)
                await self._record_delta_metrics(tenant, "changed", saved_credits, tokens)
                return outcome

            await self._record_delta_metrics(tenant, "fallback", 0, 0)
            return None
        except Exception:
            await self._record_delta_metrics(tenant, "fallback", 0, 0)
            return None

    async def _record_delta_metrics(self, tenant: str, result_type: str, credits_saved: float, tokens_saved: int):
        try:
            mkey = key(tenant, "delta", "metrics")
            pipe = self.redis.pipeline()
            pipe.hincrby(mkey, "total_checks", 1)
            pipe.hincrby(mkey, f"checks_{result_type}", 1)
            if credits_saved > 0:
                pipe.hincrbyfloat(mkey, "credits_saved", credits_saved)
            if tokens_saved > 0:
                pipe.hincrby(mkey, "tokens_used_judge_only", tokens_saved)
            await pipe.execute()
        except Exception:
            pass

    # ----- whole response -------------------------------------------------

    async def verify_response(
        self,
        tenant: str,
        response_id: str,
        text: str,
        prompt_class: str,
        policy: Policy,
        model_id: str,
        deadline_ms: int,
        cache_id: str | None,
        force: bool = False,
        trigger: str = "initial",
    ) -> tuple[dict, list[Outcome], dict]:
        clock = self.clock(tenant)
        now = await clock.now()
        deadline = time.monotonic() + max(0.1, deadline_ms / 1000)
        response = await self.repo.get(db.responses, tenant, response_id)
        annotation = dict(response["annotation"]) if response else {}
        annotation.update(
            response_id=response_id,
            tenant_id=tenant,
            cache_id=cache_id,
            policy=policy.name,
            mode="inline" if trigger == "inline" else "async",
            clock=(await clock.state()).get("mode", "real"),
            status="pending",
            min_freshness=None,
            claims=[],
            original_text=None,
            annotations_url=f"/api/v1/responses/{response_id}/annotations",
        )
        try:
            extracted, extraction_usage = await self.models.extract(text)
        except DependencyUnavailable as error:
            annotation.update(
                status="partial",
                verification_status="verification_unavailable",
                reason=str(error) or "extractor_unavailable",
                decision="fail_closed" if policy.on_unverifiable == "fail_closed" else "fail_open",
            )
            await self._store_annotation(tenant, response_id, annotation)
            return annotation, [], {}
        extraction_tokens = int(
            extraction_usage.get("input_tokens", 0) + extraction_usage.get("output_tokens", 0)
        )
        await self.buckets.take(tenant, "llm", float(extraction_tokens))
        if extraction_tokens:
            async with self.repo.database.sessions.begin() as session:
                await session.execute(
                    db.cost_ledger.insert().values(
                        id=str(uuid4()),
                        tenant_id=tenant,
                        kind="llm_tokens",
                        units=float(extraction_tokens),
                        unit_label="tokens",
                        model_id=model_id,
                    )
                )

        eligible: list[tuple[Claim, float]] = []
        skipped: list[Outcome] = []
        for claim in extracted:
            reason = skip_reason(claim)
            fkey, category = fact_key(claim)
            if reason:
                skipped.append(
                    Outcome(
                        claim=claim,
                        claim_id=str(uuid4()),
                        fact_key=fkey,
                        fact_hash=digest(fkey),
                        category=category.value,
                        status="skipped",
                        reason=reason,
                    )
                )
                continue
            p_stale = prior_stale(category, self.as_of(claim, model_id, now), now) or 0.0
            eligible.append((claim, priority(claim, p_stale)))
        eligible.sort(key=lambda pair: pair[1], reverse=True)
        eligible = eligible[: policy.max_claims_per_response]

        semaphore = asyncio.Semaphore(6)

        async def run(claim: Claim) -> Outcome:
            async with semaphore:
                if time.monotonic() >= deadline:
                    fkey, category = fact_key(claim)
                    return Outcome(
                        claim=claim,
                        claim_id=str(uuid4()),
                        fact_key=fkey,
                        fact_hash=digest(fkey),
                        category=category.value,
                        status="pending",
                        reason="deadline",
                    )
                return await self.verify_claim(tenant, claim, policy, now, model_id, deadline, force=force)

        outcomes = list(skipped) + list(await asyncio.gather(*(run(claim) for claim, _ in eligible)))
        outcomes.sort(key=lambda outcome: (outcome.claim.span or (0, 0))[0])
        checked = [outcome for outcome in outcomes if outcome.status not in ("skipped", "pending")]
        min_freshness = min((o.freshness for o in checked if o.freshness is not None), default=None)
        pending = any(outcome.status == "pending" for outcome in outcomes)
        annotation.update(
            status="partial" if pending else "complete",
            min_freshness=min_freshness,
            claims=[outcome.claim_json() for outcome in outcomes],
        )
        hard_expiry = now + timedelta(
            seconds=min(30 * DAY, max(3600, (soft_ttl(prompt_class) or DAY) * 8))
        )
        best_before = min(
            (o.next_check_at for o in outcomes if o.status in ("fresh", "due") and o.category != "static"),
            default=None,
        )
        if any(outcome.status == "stale" for outcome in outcomes):
            status = "stale"
        elif any(outcome.status == "unverifiable" for outcome in outcomes):
            status = "unverified"
        elif any(outcome.status == "due" for outcome in outcomes):
            status = "due"
        else:
            status = "fresh"
        manifest = {
            "v": 1,
            "rev": 1,
            "tenant_id": tenant,
            "cache_id": cache_id or response_id,
            "response_id": response_id,
            "model_id": model_id,
            "created_at": iso(now),
            "as_of": iso(now),
            "best_before": iso(best_before),
            "hard_expiry": iso(hard_expiry),
            "status": status,
            "policy": policy.name,
            "pinned": False,
            "claims": [outcome.manifest_json() for outcome in outcomes],
        }
        await self._persist(tenant, response_id, annotation, outcomes, manifest, cache_id, now, trigger)
        return annotation, outcomes, manifest

    async def _store_annotation(self, tenant: str, response_id: str, annotation: dict):
        async with self.repo.database.sessions.begin() as session:
            await session.execute(
                db.responses.update()
                .where(db.responses.c.tenant_id == tenant, db.responses.c.id == response_id)
                .values(annotation=annotation, annotation_status=annotation["status"])
            )

    async def _persist(
        self,
        tenant: str,
        response_id: str,
        annotation: dict,
        outcomes: list[Outcome],
        manifest: dict,
        cache_id: str | None,
        now: datetime,
        trigger: str,
    ):
        identity = cache_id or response_id
        async with self.repo.database.sessions.begin() as session:
            existing = (
                await session.execute(
                    sa.select(db.cache_entries.c.id, db.cache_entries.c.manifest_rev).where(
                        db.cache_entries.c.tenant_id == tenant,
                        db.cache_entries.c.bifrost_cache_id == identity,
                    ).with_for_update()
                )
            ).mappings().one_or_none()
            if existing:
                manifest["rev"] = int(existing["manifest_rev"] or 0) + 1
            await session.execute(
                db.claims.delete().where(
                    db.claims.c.tenant_id == tenant, db.claims.c.response_id == response_id
                )
            )
            for ordinal, outcome in enumerate(outcomes):
                fact_row = (
                    await session.execute(
                        sa.select(db.facts).where(
                            db.facts.c.tenant_id == tenant, db.facts.c.fact_key == outcome.fact_key
                        ).with_for_update()
                    )
                ).mappings().one_or_none()
                values = {
                    "fact_hash": outcome.fact_hash,
                    "class_key": outcome.category,
                    "entity": outcome.claim.entity,
                    "attribute": outcome.claim.attribute,
                    "qualifier": outcome.claim.qualifier,
                    "last_verdict": outcome.verdict,
                    "fresh_until": outcome.next_check_at,
                    "last_verified_at": now if outcome.verdict else None,
                    "interval_seconds": outcome.interval_seconds,
                    "n_checks": outcome.n_checks,
                    "n_changed": outcome.n_changed,
                    "query_hits": outcome.query_hits,
                    "lambda_hat": outcome.lambda_hat,
                    "optimal_interval_s": outcome.optimal_interval_s,
                    "ledger": {"reason": outcome.reason, "features": outcome.features},
                }
                if outcome.status in ("fresh", "due") and outcome.verdict == "confirmed":
                    values["current_value"] = outcome.claim.stated_value
                elif outcome.status == "stale":
                    values["current_value"] = outcome.corrected_value
                if fact_row:
                    fact_id = fact_row["id"]
                    values["revision"] = int(fact_row["revision"] or 0) + 1
                    await session.execute(
                        db.facts.update()
                        .where(db.facts.c.tenant_id == tenant, db.facts.c.id == fact_id)
                        .values(**values)
                    )
                else:
                    fact_id = str(uuid4())
                    await session.execute(
                        db.facts.insert().values(
                            id=fact_id,
                            tenant_id=tenant,
                            fact_key=outcome.fact_key,
                            revision=0,
                            **values,
                        )
                    )
                claim_id = outcome.claim_id
                await session.execute(
                    db.claims.insert().values(
                        id=claim_id,
                        tenant_id=tenant,
                        response_id=response_id,
                        fact_id=fact_id,
                        cache_id=identity,
                        text=outcome.claim.text,
                        entity=outcome.claim.entity,
                        attribute=outcome.claim.attribute,
                        stated_value=outcome.claim.stated_value,
                        class_key=outcome.category,
                        status=outcome.status,
                        ordinal=ordinal,
                        claim_data=outcome.claim.model_dump(mode="json"),
                        annotation=outcome.claim_json(),
                    )
                )
                if outcome.verdict is None:
                    continue
                verification_id = str(uuid4())
                # Spend is recorded at the moment it happens so the console reads
                # measured units; prices stay null until an operator configures them.
                if outcome.credits:
                    await session.execute(
                        db.cost_ledger.insert().values(
                            id=str(uuid4()),
                            tenant_id=tenant,
                            kind="tavily_credits",
                            units=outcome.credits,
                            unit_label="credits",
                            class_key=outcome.category,
                            request_id=None,
                            verification_id=verification_id,
                        )
                    )
                if outcome.tokens:
                    await session.execute(
                        db.cost_ledger.insert().values(
                            id=str(uuid4()),
                            tenant_id=tenant,
                            kind="llm_tokens",
                            units=float(outcome.tokens),
                            unit_label="tokens",
                            model_id=manifest.get("model_id"),
                            verification_id=verification_id,
                        )
                    )
                await session.execute(
                    db.verifications.insert().values(
                        id=verification_id,
                        tenant_id=tenant,
                        fact_id=fact_id,
                        claim_id=claim_id,
                        trigger_kind=trigger,
                        verdict=outcome.verdict,
                        effective_verdict=outcome.verdict,
                        status=outcome.status,
                        corrected_value=outcome.corrected_value,
                        rationale=(outcome.reason or "")[:280],
                        judge_confidence=outcome.support_confidence,
                        freshness=outcome.freshness,
                        support_confidence=outcome.support_confidence,
                        features=outcome.features,
                        queries=None,
                        latency_ms=outcome.latency_ms,
                        tavily_credits=outcome.credits,
                        finished_at=now,
                    )
                )
                for evidence in outcome.evidence[:6]:
                    if evidence.id in outcome.contradict_ids:
                        label = "contradicts"
                    elif evidence.id in outcome.support_ids:
                        label = "supports"
                    else:
                        label = "candidate"
                    await session.execute(
                        db.evidence.insert().values(
                            id=str(uuid4()),
                            tenant_id=tenant,
                            verification_id=verification_id,
                            url=evidence.url,
                            domain=evidence.domain,
                            title=evidence.title,
                            snippet=evidence.snippet,
                            published_at=evidence.published_at,
                            retrieved_at=evidence.retrieved_at,
                            authority_tier=evidence.tier,
                            source=evidence.source,
                            label=label,
                        )
                    )
                if cache_id:
                    await self.redis.sadd(key(tenant, "idx", "fact:" + outcome.fact_hash), cache_id)
            await session.execute(
                db.responses.update()
                .where(db.responses.c.tenant_id == tenant, db.responses.c.id == response_id)
                .values(annotation=annotation, annotation_status=annotation["status"])
            )
            entry_values = {
                "response_id": response_id,
                "status": manifest["status"],
                "best_before": parse_time(manifest["best_before"]),
                "hard_expiry": parse_time(manifest["hard_expiry"]),
                "manifest_rev": manifest["rev"],
                "manifest": manifest,
            }
            if existing:
                await session.execute(
                    db.cache_entries.update()
                    .where(db.cache_entries.c.tenant_id == tenant, db.cache_entries.c.id == existing["id"])
                    .values(**entry_values)
                )
            else:
                # Two equivalent requests can finish verification together; the
                # second insert must land on the row the first one created
                # instead of failing the whole manifest write.
                try:
                    async with session.begin_nested():
                        await session.execute(
                            db.cache_entries.insert().values(
                                id=str(uuid4()),
                                tenant_id=tenant,
                                bifrost_cache_id=identity,
                                **entry_values,
                            )
                        )
                except IntegrityError:
                    await session.execute(
                        db.cache_entries.update()
                        .where(
                            db.cache_entries.c.tenant_id == tenant,
                            db.cache_entries.c.bifrost_cache_id == identity,
                        )
                        .values(**entry_values)
                    )
            await self.repo.event(
                tenant,
                "verification.finished",
                {
                    "response_id": response_id,
                    "verdict": manifest["status"],
                    "claim_count": len(outcomes),
                    "min_freshness": annotation.get("min_freshness"),
                },
                session,
            )
        await self.redis.set(key(tenant, "manifest", identity), json.dumps(manifest))
        if cache_id:
            await self.redis.set(key(tenant, "manifest", response_id), json.dumps(manifest))

    # ----- revalidation ---------------------------------------------------

    async def revalidate(
        self,
        tenant: str,
        cache_id: str,
        policy: Policy,
        deadline_ms: int,
        reason: str,
        force: bool,
    ) -> dict:
        raw = await self.redis.get(key(tenant, "manifest", cache_id))
        if not raw:
            return {
                "status": "failed",
                "decision": "unverifiable",
                "annotation": None,
                "pending_fact_ids": [],
                "replacement": None,
            }
        manifest = json.loads(raw)
        now = await self.clock(tenant).now()
        due = []
        for item in manifest.get("claims", []):
            if item.get("status") in ("skipped", "unverifiable", "pending"):
                continue
            check = parse_time(item.get("next_check_at"))
            if force or reason == "manual" or check is None or check <= now:
                due.append(item)
        if not due:
            return {
                "status": "complete",
                "decision": "serve",
                "annotation": self._manifest_annotation(manifest),
                "pending_fact_ids": [],
                "replacement": None,
            }
        deadline = time.monotonic() + max(0.1, deadline_ms / 1000)
        results: dict[str, Outcome] = {}
        for item in due[:6]:
            claim = Claim(
                text=item.get("text", ""),
                entity=item.get("entity", ""),
                entity_type=item.get("entity_type", "other"),
                attribute=item.get("attribute", "other"),
                stated_value=item.get("stated_value", ""),
                qualifier=item.get("qualifier"),
                class_key=item["class"],
                importance=float(item.get("importance", 0.5)),
                as_of_hint=item.get("as_of_hint"),
            )
            outcome = await self.verify_claim(
                tenant, claim, policy, now, manifest.get("model_id", ""), deadline, force=True
            )
            outcome.claim_id = item.get("claim_id", outcome.claim_id)
            results[outcome.fact_hash] = outcome
        pending = []
        for item in manifest.get("claims", []):
            outcome = results.get(item.get("fact_key_hash") or digest(item.get("fact_key", "")))
            if outcome is None:
                continue
            item.update(
                status=outcome.status,
                freshness=outcome.freshness,
                verdict=outcome.verdict,
                corrected_value=outcome.corrected_value,
                next_check_at=iso(outcome.next_check_at),
                verified_at=iso(outcome.verified_at),
            )
            if outcome.status == "pending":
                pending.append(outcome.fact_hash)
        best = min(
            (
                parse_time(item.get("next_check_at"))
                for item in manifest.get("claims", [])
                if item.get("status") in ("fresh", "due")
                and item.get("class") != "static"
                and item.get("next_check_at")
            ),
            default=None,
        )
        manifest["best_before"] = iso(best)
        states = [item.get("status") for item in manifest.get("claims", [])]
        if "stale" in states:
            manifest["status"] = "stale"
        elif "unverifiable" in states:
            manifest["status"] = "unverified"
        elif "due" in states:
            manifest["status"] = "due"
        else:
            manifest["status"] = "fresh"
        manifest["rev"] = int(manifest.get("rev") or 0) + 1
        await self.redis.set(key(tenant, "manifest", cache_id), json.dumps(manifest))
        await self._update_entry(tenant, cache_id, manifest)
        if manifest["status"] == "stale":
            decision = "evict_regen" if policy.regen_on_stale else "evict_lazy"
        elif manifest["status"] == "unverified":
            decision = "unverifiable"
        else:
            decision = "serve"
        replacement = None
        if decision == "evict_regen":
            ground_id = str(uuid4())
            stale_claims = [c for c in manifest.get("claims", []) if c.get("status") == "stale"]
            ground_bundle = {
                "ground_id": ground_id,
                "cache_id": cache_id,
                "facts": [
                    {
                        "fact_key": c.get("fact_key"),
                        "old_value": c.get("stated_value"),
                        "new_value": c.get("corrected_value"),
                        "as_of": c.get("verified_at"),
                    }
                    for c in stale_claims
                ],
                "evidence": [
                    evidence.model_dump(mode="json")
                    for outcome in results.values()
                    for evidence in outcome.evidence[:4]
                ],
                "instruction": "The previous answer contained outdated claims. Regenerate the answer using the verified updated facts and evidence.",
            }
            await self.redis.set(key(tenant, "ground", ground_id), json.dumps(ground_bundle), ex=600)
            replacement = {
                "ground_id": ground_id,
                "instruction": ground_bundle["instruction"],
                "facts": ground_bundle["facts"],
            }
        await self.repo.event(
            tenant,
            "entry.status_changed",
            {"cache_id": cache_id, "from": reason, "to": manifest["status"]},
        )
        return {
            "status": "partial" if pending else "complete",
            "decision": decision,
            "annotation": self._manifest_annotation(manifest),
            "pending_fact_ids": pending,
            "replacement": replacement,
        }

    async def _update_entry(self, tenant: str, cache_id: str, manifest: dict):
        async with self.repo.database.sessions.begin() as session:
            await session.execute(
                db.cache_entries.update()
                .where(
                    db.cache_entries.c.tenant_id == tenant,
                    db.cache_entries.c.bifrost_cache_id == cache_id,
                )
                .values(
                    status=manifest["status"],
                    best_before=parse_time(manifest.get("best_before")),
                    manifest_rev=manifest["rev"],
                    manifest=manifest,
                )
            )

    def _manifest_annotation(self, manifest: dict) -> dict:
        claims = [
            {
                "claim_id": item.get("claim_id"),
                "fact_key": item.get("fact_key"),
                "text": item.get("text"),
                "status": item.get("status"),
                "freshness": item.get("freshness"),
                "verdict": item.get("verdict"),
                "corrected_value": item.get("corrected_value"),
                "next_check_at": item.get("next_check_at"),
            }
            for item in manifest.get("claims", [])
        ]
        values = [claim["freshness"] for claim in claims if claim["freshness"] is not None]
        status = manifest.get("status")
        return {
            "response_id": manifest.get("response_id"),
            "cache_id": manifest.get("cache_id"),
            "decision": "serve" if status in ("fresh", "due") else "evict_regen" if status == "stale" else "fail_closed",
            "cache": "hit",
            "mode": "manifest",
            "status": "complete",
            "clock": "real",
            "min_freshness": min(values) if values else None,
            "policy": manifest.get("policy"),
            "claims": claims,
            "annotations_url": f"/api/v1/responses/{manifest.get('response_id')}/annotations",
        }
