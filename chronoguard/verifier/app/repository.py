import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.schemas.contracts import POLICIES, Ingest
from app.security import digest


class Repository:
    def __init__(self, database):
        self.database = database

    async def event(self, tenant, kind, payload, session=None):
        if session is not None:
            await session.execute(db.events.insert().values(tenant_id=tenant, type=kind, payload=payload))
        else:
            async with self.database.sessions.begin() as session:
                await self.event(tenant, kind, payload, session)

    async def seed(self, tenant):
        async with self.database.sessions.begin() as session:
            try:
                await session.execute(sa.text("ALTER TABLE requests ADD COLUMN IF NOT EXISTS decision_shadow VARCHAR(32)"))
                await session.execute(sa.text("ALTER TABLE requests ADD COLUMN IF NOT EXISTS shadow_reason TEXT"))
            except Exception:
                pass
            existing = set((await session.execute(sa.select(db.policies.c.name).where(db.policies.c.tenant_id == tenant))).scalars())
            for name, policy in POLICIES.items():
                if name not in existing:
                    await session.execute(db.policies.insert().values(tenant_id=tenant, name=name, config=policy.model_dump()))

    async def ingest(self, data: Ingest, store_content=False, queue=True):
        tenant = data.tenant_id
        async def existing(session):
            return (await session.execute(sa.select(db.responses.c.id).join(db.requests, db.responses.c.request_id == db.requests.c.id).where(db.requests.c.tenant_id == tenant, db.requests.c.bifrost_request_id == data.request_id))).scalar_one_or_none()
        try:
            async with self.database.sessions.begin() as session:
                previous = await existing(session)
                if previous:
                    return previous, False
                request_id, response_id = str(uuid4()), str(uuid4())
                messages = [m.model_dump() for m in data.messages]
                decision_shadow = getattr(data, "decision_shadow", None)
                shadow_reason = getattr(data, "shadow_reason", None)
                guard_tripped = getattr(data, "guard_tripped", False)
                guard_reason = getattr(data, "guard_reason", None)
                query_signature = getattr(data, "query_signature", None)
                await session.execute(db.requests.insert().values(id=request_id, tenant_id=tenant, bifrost_request_id=data.request_id, model_id=data.model_id, provider=data.provider, prompt_hash=digest(json.dumps(messages, sort_keys=True)), messages=messages if store_content else None, policy=data.policy, prompt_class=data.prompt_class, cache_status="miss", cache_id=data.cache_id, decision="passthrough", decision_shadow=decision_shadow, shadow_reason=shadow_reason, guard_tripped=guard_tripped, guard_reason=guard_reason, query_signature=query_signature))
                annotation = {"response_id":response_id, "tenant_id":tenant, "decision":"passthrough", "cache":"miss", "cache_id":data.cache_id, "mode":"async", "status":"pending", "clock":"real", "min_freshness":None, "policy":data.policy, "claims":[], "original_text":None, "annotations_url":f"/api/v1/responses/{response_id}/annotations"}
                await session.execute(db.responses.insert().values(id=response_id, tenant_id=tenant, request_id=request_id, origin=data.origin, content=data.response_text if store_content else None, content_hash=digest(data.response_text), model_id=data.model_id, input_tokens=data.usage.input_tokens, output_tokens=data.usage.output_tokens, annotation_status="pending", annotation=annotation))
                # The payload is transient job state, cleared when the job finishes;
                # storing content is a separate, longer-lived decision. Inline
                # verification does not enqueue a job it would duplicate.
                if queue:
                    await session.execute(db.jobs.insert().values(tenant_id=tenant, response_id=response_id, state="queued", payload=data.model_dump(mode="json")))
                await self.event(tenant, "request.completed", {"request_id":request_id, "response_id":response_id, "model":data.model_id, "cache_status":"miss", "decision":"passthrough"}, session)
                return response_id, True
        except IntegrityError:
            async with self.database.sessions() as session:
                previous = await existing(session)
                if previous:
                    return previous, False
            raise

    async def record_hit(self, tenant: str, request_id: str, model_id: str, cache_id: str, policy: str, prompt_class: str, decision: str = "serve", decision_shadow: str | None = None, shadow_reason: str | None = None, guard_tripped: bool = False, guard_reason: str | None = None, query_signature: str | None = None, latency_ms: int = 1):
        try:
            async with self.database.sessions.begin() as session:
                req_id = str(uuid4())
                await session.execute(db.requests.insert().values(
                    id=req_id,
                    tenant_id=tenant,
                    bifrost_request_id=request_id,
                    model_id=model_id,
                    provider="",
                    prompt_hash=digest(request_id),
                    messages=None,
                    policy=policy,
                    prompt_class=prompt_class,
                    cache_status="hit_semantic" if "semantic" in decision else "hit_direct",
                    cache_id=cache_id,
                    decision=decision,
                    decision_shadow=decision_shadow,
                    shadow_reason=shadow_reason,
                    guard_tripped=guard_tripped,
                    guard_reason=guard_reason,
                    query_signature=query_signature,
                    total_latency_ms=latency_ms,
                    hook_overhead_us=120,
                ))
                await self.event(tenant, "request.completed", {
                    "request_id": req_id,
                    "model": model_id,
                    "cache_status": "hit",
                    "decision": decision,
                    "decision_shadow": decision_shadow,
                }, session)
                return req_id
        except Exception:
            return None

    async def get_policy(self, tenant, name):
        async with self.database.sessions() as session:
            row = (await session.execute(sa.select(db.policies.c.config).where(db.policies.c.tenant_id == tenant, db.policies.c.name == name))).scalar_one_or_none()
            return dict(row) if row else None

    def present(self, table, row):
        """Flatten stored configuration for the API, without hiding the row id."""
        item = dict(row)
        if table is db.policies:
            item = {**dict(item.get("config") or {}), **{k: v for k, v in item.items() if k != "config"}}
        return item

    async def get(self, table, tenant, identity):
        async with self.database.sessions() as session:
            row = (await session.execute(sa.select(table).where(table.c.tenant_id == tenant, table.c.id == identity))).mappings().one_or_none()
            return self.present(table, row) if row else None

    async def list(self, table, tenant, limit=50, cursor=None, filters=None):
        query = sa.select(table).where(table.c.tenant_id == tenant)
        if cursor:
            query = query.where(table.c.id < cursor)
        for column, value in (filters or {}).items():
            if value is not None and column in table.c:
                query = query.where(table.c[column] == value)
        query = query.order_by(table.c.id.desc()).limit(limit+1)
        async with self.database.sessions() as session:
            rows = [self.present(table, r) for r in (await session.execute(query)).mappings()]
            if table is db.requests and rows:
                request_ids = [row["id"] for row in rows]
                responses = (await session.execute(sa.select(db.responses).where(db.responses.c.tenant_id == tenant, db.responses.c.request_id.in_(request_ids)))).mappings().all()
                by_request = {row["request_id"]: row for row in responses}
                response_ids = [row["id"] for row in responses]
                counts = {}
                if response_ids:
                    counts = dict((await session.execute(sa.select(db.claims.c.response_id, sa.func.count()).where(db.claims.c.tenant_id == tenant, db.claims.c.response_id.in_(response_ids)).group_by(db.claims.c.response_id))).all())
                for row in rows:
                    response = by_request.get(row["id"])
                    annotation = dict((response or {}).get("annotation") or {})
                    row["response_id"] = response["id"] if response else None
                    row["min_freshness"] = annotation.get("min_freshness")
                    row["claim_count"] = counts.get(response["id"], len(annotation.get("claims") or [])) if response else 0
                    messages = row.get("messages") or []
                    preview = next((message.get("content") for message in messages if message.get("role") == "user"), None)
                    row["prompt_preview"] = preview[:160] if preview else "Content not stored"
            if table is db.cache_entries:
                for row in rows:
                    manifest = dict(row.get("manifest") or {})
                    claims = manifest.get("claims") or []
                    row["claim_count"] = len(claims)
                    verified = [claim.get("verified_at") for claim in claims if claim.get("verified_at")]
                    row["last_verified_at"] = max(verified) if verified else None
                    row["prompt_preview"] = row.get("bifrost_cache_id")
                    row["classes"] = sorted({claim.get("class") for claim in claims if claim.get("class")})
            if table is db.facts and rows:
                fact_ids = [row["id"] for row in rows]
                counts = dict((await session.execute(sa.select(db.claims.c.fact_id, sa.func.count(sa.distinct(db.claims.c.cache_id))).where(db.claims.c.tenant_id == tenant, db.claims.c.fact_id.in_(fact_ids)).group_by(db.claims.c.fact_id))).all())
                for row in rows:
                    row["entries_affected"] = counts.get(row["id"], 0)
                    row["interval_s"] = row.get("interval_seconds")
        return {"items": rows[:limit], "next_cursor":str(rows[limit-1]["id"]) if len(rows)>limit else None}

    async def cache_entry(self, tenant, identity):
        """Entry detail with the records an operator needs to explain it."""
        row = await self.get(db.cache_entries, tenant, identity)
        if row is None:
            return None
        async with self.database.sessions() as session:
            response = None
            if row.get("response_id"):
                response = (await session.execute(sa.select(db.responses).where(db.responses.c.tenant_id == tenant, db.responses.c.id == row["response_id"]))).mappings().one_or_none()
            claim_rows = (await session.execute(sa.select(db.claims).where(db.claims.c.tenant_id == tenant, db.claims.c.cache_id == row["bifrost_cache_id"]).order_by(db.claims.c.ordinal))).mappings().all()
            claim_ids = [claim["id"] for claim in claim_rows]
            checks = []
            if claim_ids:
                checks = (await session.execute(sa.select(db.verifications).where(db.verifications.c.tenant_id == tenant, db.verifications.c.claim_id.in_(claim_ids)).order_by(db.verifications.c.created_at.desc()))).mappings().all()
        claims = []
        for claim in claim_rows:
            annotation = dict(claim.get("annotation") or {})
            annotation.update(claim_id=claim["id"], fact_id=claim.get("fact_id"), reviewed_at=claim.get("reviewed_at"))
            claims.append(annotation)
        history = [{"at": row["created_at"], "event": "created", "detail": "Manifest written for this cache key"}]
        for claim in claims:
            if claim.get("verified_at"):
                history.append({"at": claim["verified_at"], "event": "verified", "detail": claim.get("text")})
        history.sort(key=lambda item: str(item["at"] or ""))
        return {
            **row,
            "content": response["content"] if response else None,
            "content_stored": bool(response and response["content"]),
            "model_id": (response or {}).get("model_id") or (row.get("manifest") or {}).get("model_id"),
            "claims": claims,
            "verifications": [dict(check) for check in checks],
            "history": history,
        }

    async def claim_detail(self, tenant, identity):
        row = await self.get(db.claims, tenant, identity)
        if row is None:
            return None
        async with self.database.sessions() as session:
            checks = (await session.execute(sa.select(db.verifications).where(db.verifications.c.tenant_id == tenant, db.verifications.c.claim_id == identity).order_by(db.verifications.c.created_at.desc()))).mappings().all()
            evidence_rows = []
            if checks:
                evidence_rows = (await session.execute(sa.select(db.evidence).where(db.evidence.c.tenant_id == tenant, db.evidence.c.verification_id.in_([check["id"] for check in checks])).order_by(db.evidence.c.authority_tier, db.evidence.c.created_at.desc()))).mappings().all()
            fact = None
            if row.get("fact_id"):
                fact = (await session.execute(sa.select(db.facts).where(db.facts.c.tenant_id == tenant, db.facts.c.id == row["fact_id"]))).mappings().one_or_none()
            entries = []
            if row.get("fact_id"):
                sibling_cache_ids = sa.select(db.claims.c.cache_id).where(db.claims.c.tenant_id == tenant, db.claims.c.fact_id == row["fact_id"], db.claims.c.cache_id.isnot(None))
                entries = (await session.execute(sa.select(db.cache_entries).where(db.cache_entries.c.tenant_id == tenant, db.cache_entries.c.bifrost_cache_id.in_(sibling_cache_ids)))).mappings().all()
        annotation = dict(row.get("annotation") or {})
        annotation.update(
            claim_id=row["id"],
            response_id=row["response_id"],
            fact_id=row.get("fact_id"),
            fact_key=(fact or {}).get("fact_key"),
            entity=row.get("entity"),
            attribute=row.get("attribute"),
            stated_value=row.get("stated_value"),
            class_key=row.get("class_key"),
            reviewed_at=row.get("reviewed_at"),
            evidence=[dict(item) for item in evidence_rows],
            verifications=[dict(check) for check in checks],
            features=(checks[0].get("features") if checks else None),
            rationale=(checks[0].get("rationale") if checks else None),
            entries=[{"id": entry["id"], "status": entry["status"], "best_before": entry["best_before"]} for entry in entries],
        )
        return annotation

    async def annotation(self, tenant, response_id):
        row = await self.get(db.responses, tenant, response_id)
        return row["annotation"] if row else None

    async def mark_unavailable(self, tenant, response_id, reason):
        async with self.database.sessions.begin() as session:
            row = (await session.execute(sa.select(db.responses).where(db.responses.c.tenant_id == tenant, db.responses.c.id == response_id).with_for_update())).mappings().one()
            annotation = dict(row["annotation"])
            annotation.update(status="partial", decision="fail_closed" if annotation["policy"] == "strict" else "fail_open", verification_status="verification_unavailable", reason=reason)
            await session.execute(db.responses.update().where(db.responses.c.tenant_id == tenant, db.responses.c.id == response_id).values(annotation_status="failed", annotation=annotation))
            await session.execute(db.jobs.update().where(db.jobs.c.tenant_id == tenant, db.jobs.c.response_id == response_id).values(state="failed", error_code=reason, finished_at=db.now()))
            await self.event(tenant, "verification.finished", {"response_id":response_id,"verdict":"unverifiable","reason":reason}, session)
        return annotation

    async def costs(self, tenant, hours=24):
        start = datetime.now(UTC) - timedelta(hours=hours)
        async with self.database.sessions() as session:
            rows = (await session.execute(sa.select(db.cost_ledger).where(db.cost_ledger.c.tenant_id == tenant, db.cost_ledger.c.created_at >= start))).mappings().all()
            facts = (await session.execute(
                sa.select(db.facts.c.fact_key, sa.func.sum(db.verifications.c.tavily_credits).label("credits"), sa.func.count(db.verifications.c.id).label("checks"))
                .join(db.verifications, db.verifications.c.fact_id == db.facts.c.id)
                .where(db.facts.c.tenant_id == tenant, db.verifications.c.created_at >= start)
                .group_by(db.facts.c.fact_key).order_by(sa.desc(sa.func.sum(db.verifications.c.tavily_credits))).limit(10)
            )).mappings().all()

        saved_kinds = {"tokens_saved", "cache_saved", "saved"}
        by_kind: dict[str, dict] = {}
        by_class: dict[str, dict] = {}
        by_day: dict[str, dict] = {}
        saved = spent = 0.0
        saved_priced = spent_priced = True
        priced_rows = 0
        for row in rows:
            kind = row["kind"]
            usd = row["usd"]
            if usd is not None:
                priced_rows += 1
            amount = float(usd or 0.0)
            bucket = by_kind.setdefault(kind, {"units": 0.0, "usd": 0.0, "priced": True})
            bucket["units"] += float(row["units"] or 0.0)
            if usd is None:
                bucket["priced"] = False
                bucket["usd"] = None
            elif bucket["usd"] is not None:
                bucket["usd"] += amount
            if kind in saved_kinds:
                saved += amount
                saved_priced = saved_priced and usd is not None
            else:
                spent += amount
                spent_priced = spent_priced and usd is not None
            if row["class_key"]:
                klass = by_class.setdefault(row["class_key"], {"units": 0.0, "usd": 0.0, "priced": True})
                klass["units"] += float(row["units"] or 0.0)
                if usd is None:
                    klass["priced"] = False
                    klass["usd"] = None
                elif klass["usd"] is not None:
                    klass["usd"] += amount
            day = row["created_at"].date().isoformat()
            daily = by_day.setdefault(day, {"day": day, "saved_usd": 0.0, "spent_usd": 0.0, "priced": True})
            if usd is None:
                daily["priced"] = False
            elif kind in saved_kinds:
                daily["saved_usd"] += amount
            else:
                daily["spent_usd"] += amount

        # A sum that silently treats unknown prices as zero would be a fabricated
        # saving; leave it null and say why instead.
        savings_complete = saved_priced and any(row["kind"] in saved_kinds for row in rows)
        spend_complete = spent_priced and any(row["kind"] not in saved_kinds for row in rows)
        net = (saved - spent) if savings_complete and spend_complete else None
        return {
            "window_hours": hours,
            "saved_usd": saved if savings_complete else None,
            "spent_usd": spent if spend_complete else None,
            "net_usd": net,
            "reconciliation_delta_usd": None,
            "pricing_complete": priced_rows == len(rows) and bool(rows),
            "by_kind": {name: value for name, value in by_kind.items()},
            "by_class": by_class,
            "by_day": [by_day[day] for day in sorted(by_day)],
            "facts": [dict(row) for row in facts],
            "items": [dict(row) for row in rows],
        }
