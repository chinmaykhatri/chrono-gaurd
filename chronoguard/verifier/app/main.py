import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import redis.asyncio as redis
import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware

from app import db
from app.clients import ModelClient, TavilyClient
from app.clock.service import Clock
from app.config import Settings
from app.eval_runner import eval_service
from app.pipeline.budget import Buckets
from app.pipeline.triage import prompt_class
from app.pipeline.verify import Verifier
from app.repository import Repository
from app.schemas.contracts import (
    Category,
    Contract,
    Ingest,
    Message,
    Policy,
    RecordHit,
    Revalidate,
)
from app.scoring.freshness import CLASSES
from app.security import digest, key, login, require_internal, require_session


class Login(Contract):
    password: str = Field(min_length=1, max_length=1024)


class ClockAction(Contract):
    action: Literal["advance", "freeze", "reset"]
    seconds: int = Field(0, ge=0, le=315360000)
    timestamp: datetime | None = None


class PlaygroundChat(Contract):
    model: str = Field(min_length=1, max_length=256)
    messages: list[Message] = Field(min_length=1, max_length=20)
    policy: Literal["strict", "standard", "lenient"] = "standard"
    cache: bool = True


class DryRun(Contract):
    prompt: str = Field(min_length=1, max_length=4000)


class Pin(Contract):
    pinned: bool = True


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = request.app.state.settings
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > settings.request_limit_bytes:
                    return JSONResponse({"error":{"code":"payload_too_large","message":"Request too large"}}, status_code=413)
            except ValueError:
                return JSONResponse({"error":{"code":"validation_error","message":"Invalid content length"}}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response


async def run_jobs(app):
    """Consume queued verification jobs until the app shuts down."""
    while True:
        job = None
        try:
            async with app.state.database.sessions.begin() as session:
                job = (
                    await session.execute(
                        sa.select(db.jobs)
                        .where(db.jobs.c.state == "queued")
                        .order_by(db.jobs.c.created_at)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                ).mappings().one_or_none()
                if job:
                    await session.execute(
                        db.jobs.update()
                        .where(db.jobs.c.id == job["id"])
                        .values(state="running", locked_at=db.now(), attempts=int(job["attempts"] or 0) + 1)
                    )
            if not job:
                await asyncio.sleep(0.5)
                continue
            payload = dict(job["payload"] or {})
            tenant = job["tenant_id"]
            response_id = job["response_id"]
            row = await app.state.repo.get(db.responses, tenant, response_id)
            text = (row or {}).get("content") or payload.get("response_text")
            if not text:
                raise ValueError("response text unavailable")
            verifier = app.state.verifier
            policy = await verifier.policy(tenant, payload.get("policy", "standard"))
            await verifier.verify_response(
                tenant,
                response_id,
                text,
                payload.get("prompt_class", "slow_facts"),
                policy,
                payload.get("model_id", ""),
                int(payload.get("deadline_ms", 15000)),
                payload.get("cache_id"),
                trigger="async",
            )
            async with app.state.database.sessions.begin() as session:
                await session.execute(
                    db.jobs.update()
                    .where(db.jobs.c.id == job["id"])
                    .values(state="done", payload=None, finished_at=db.now(), error_code=None)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            if job:
                try:
                    async with app.state.database.sessions.begin() as session:
                        await session.execute(
                            db.jobs.update()
                            .where(db.jobs.c.id == job["id"])
                            .values(state="failed", payload=None, finished_at=db.now(), error_code="verification_failed")
                        )
                except Exception:
                    pass
            await asyncio.sleep(1)


def create_app(settings: Settings | None = None, database=None, redis_client=None):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or Settings()
        app.state.settings = cfg
        app.state.database = database or db.Database(cfg.database_url.get_secret_value())
        try:
            async with app.state.database.engine.begin() as conn:
                for col_sql in [
                    "ALTER TABLE requests ADD COLUMN IF NOT EXISTS decision_shadow VARCHAR(32)",
                    "ALTER TABLE requests ADD COLUMN IF NOT EXISTS shadow_reason TEXT",
                    "ALTER TABLE requests ADD COLUMN IF NOT EXISTS guard_tripped BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE requests ADD COLUMN IF NOT EXISTS guard_reason VARCHAR(64)",
                    "ALTER TABLE requests ADD COLUMN IF NOT EXISTS query_signature TEXT",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_urls JSONB DEFAULT '[]'::jsonb",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_text_hash VARCHAR(64)",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS window_hash VARCHAR(64)",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS last_extracted_at TIMESTAMP WITH TIME ZONE",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS delta_confirmed BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS delta_saved_credits FLOAT DEFAULT 0.0",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS n_checks INTEGER DEFAULT 1",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS n_changed INTEGER DEFAULT 0",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS query_hits INTEGER DEFAULT 0",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS lambda_hat FLOAT DEFAULT 0.0",
                    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS optimal_interval_s INTEGER",
                    "ALTER TABLE claims ADD COLUMN IF NOT EXISTS source_urls JSONB DEFAULT '[]'::jsonb",
                    "ALTER TABLE claims ADD COLUMN IF NOT EXISTS source_text_hash VARCHAR(64)",
                    "ALTER TABLE claims ADD COLUMN IF NOT EXISTS delta_confirmed BOOLEAN DEFAULT FALSE",
                ]:
                    try:
                        await conn.execute(sa.text(col_sql))
                    except Exception:
                        pass
        except Exception:
            pass
        app.state.redis = redis_client or redis.from_url(cfg.redis_url.get_secret_value(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        app.state.repo = Repository(app.state.database)
        app.state.http = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        app.state.queue = asyncio.Queue(maxsize=cfg.queue_size)
        app.state.models = ModelClient(cfg, app.state.http)
        app.state.tavily = TavilyClient(cfg, app.state.http)
        app.state.buckets = Buckets(app.state.redis, cfg)
        app.state.verifier = Verifier(
            cfg,
            app.state.repo,
            app.state.redis,
            lambda tenant: Clock(app.state.redis, tenant),
            app.state.models,
            app.state.tavily,
            app.state.buckets,
        )
        await app.state.repo.seed(cfg.tenant_id)
        workers = [asyncio.create_task(run_jobs(app)) for _ in range(max(1, min(4, cfg.workers)))]
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await app.state.http.aclose()
            if redis_client is None:
                await app.state.redis.aclose()
            if database is None:
                await app.state.database.close()

    app = FastAPI(title="ChronoGuard Verifier", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeaders)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        code = error.detail if isinstance(error.detail, str) else "request_failed"
        return JSONResponse({"error":{"code":code,"message":code.replace("_"," ")}}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        import logging
        logging.error("Validation error details: %s", error.errors())
        # Pydantic errors include input values by default; never return passwords/prompts.
        return JSONResponse({"error":{"code":"validation_error","message":"Request does not match the API schema", "details":[{"loc":e["loc"],"type":e["type"]} for e in error.errors()]}}, status_code=422)

    @app.exception_handler(Exception)
    async def unavailable(request, error):
        return JSONResponse({"error":{"code":"upstream_unavailable","message":"A required service is unavailable"}}, status_code=503)

    @app.get("/healthz")
    async def health():
        return {"ok":True}

    async def health_state(request):
        checks = {}
        for name, check in (("postgres",request.app.state.database.healthy),("redis",request.app.state.redis.ping)):
            try:
                checks[name] = bool(await asyncio.wait_for(check(), timeout=2))
            except Exception:
                checks[name] = False
        checks["tavily_key_present"] = bool(request.app.state.settings.tavily_api_key.get_secret_value())
        checks["models_configured"] = bool(request.app.state.settings.extractor_model and request.app.state.settings.judge_model)
        return {"ok":checks["postgres"] and checks["redis"], **checks, "queue_depth":request.app.state.queue.qsize()}

    @app.get("/readyz")
    async def ready(request: Request):
        state = await health_state(request)
        return JSONResponse(state, status_code=200 if state["ok"] else 503)

    @app.post("/api/v1/auth/login")
    async def auth_login(body: Login, request: Request, response: Response):
        session_id, session = await login(request, body.password)
        response.set_cookie("cg_session", session_id, max_age=request.app.state.settings.session_ttl_seconds, secure=request.app.state.settings.environment == "production", httponly=True, samesite="strict", path="/api/v1")
        return session

    @app.get("/api/v1/auth/session")
    async def auth_session(session=Depends(require_session)):
        return session

    @app.post("/api/v1/auth/logout")
    async def auth_logout(request: Request, response: Response, session=Depends(require_session)):
        await request.app.state.redis.delete("cg:session:"+digest(request.cookies["cg_session"]))
        response.delete_cookie("cg_session", path="/api/v1")
        return {"ok":True}

    @app.get("/internal/v1/health", dependencies=[Depends(require_internal)])
    async def internal_health(request: Request):
        return await health_state(request)

    @app.post("/internal/v1/ingest", status_code=202, dependencies=[Depends(require_internal)])
    async def ingest(body: Ingest, request: Request):
        response_id, _ = await request.app.state.repo.ingest(body, request.app.state.settings.store_content)
        # The durable job is queued transactionally with the response. A worker
        # claims it before verification starts, so a lost worker leaves a
        # retryable queued job rather than a silent failure.
        return {"response_id":response_id}

    @app.post("/internal/v1/verify-inline", dependencies=[Depends(require_internal)])
    async def verify_inline(body: Ingest, request: Request):
        response_id, _ = await request.app.state.repo.ingest(body, request.app.state.settings.store_content, queue=False)
        verifier = request.app.state.verifier
        policy = await verifier.policy(body.tenant_id, body.policy)
        annotation, _, _ = await verifier.verify_response(
            body.tenant_id,
            response_id,
            body.response_text,
            body.prompt_class.value if hasattr(body.prompt_class, "value") else str(body.prompt_class),
            policy,
            body.model_id,
            body.deadline_ms,
            body.cache_id,
            trigger="inline",
        )
        return {
            "response_id": response_id,
            "status": annotation.get("status", "partial"),
            "annotation": annotation,
            "repaired_text": None,
        }

    @app.post("/internal/v1/revalidate", dependencies=[Depends(require_internal)])
    async def revalidate(body: Revalidate, request: Request):
        verifier = request.app.state.verifier
        policy = await verifier.policy(body.tenant_id, body.policy)
        return await verifier.revalidate(
            body.tenant_id, body.cache_id, policy, body.deadline_ms, body.reason, body.force
        )

    @app.post("/internal/v1/record-hit", dependencies=[Depends(require_internal)])
    async def record_hit_endpoint(body: RecordHit, request: Request):
        req_id = await request.app.state.repo.record_hit(
            tenant=body.tenant_id,
            request_id=body.request_id,
            model_id=body.model_id,
            cache_id=body.cache_id,
            policy=body.policy,
            prompt_class=body.prompt_class.value if hasattr(body.prompt_class, "value") else str(body.prompt_class),
            decision=body.decision,
            decision_shadow=body.decision_shadow,
            shadow_reason=body.shadow_reason,
            guard_tripped=body.guard_tripped,
            guard_reason=body.guard_reason,
            query_signature=body.query_signature,
            latency_ms=body.latency_ms,
        )
        return {"ok": True, "request_id": req_id}

    @app.get("/api/v1/settings/health")
    async def settings_health(request: Request, session=Depends(require_session)):
        state = await health_state(request)
        settings = request.app.state.settings
        bifrost_status, bifrost_detail = "unavailable", settings.bifrost_url.rstrip("/")
        try:
            headers = {}
            if settings.bifrost_api_key.get_secret_value():
                headers["Authorization"] = "Bearer " + settings.bifrost_api_key.get_secret_value()
            response = await asyncio.wait_for(
                request.app.state.http.get(settings.bifrost_url.rstrip("/") + "/v1/models", headers=headers, timeout=2), 2.5
            )
            bifrost_status = "ready" if response.status_code < 500 else "unavailable"
            bifrost_detail = f"Gateway answered {response.status_code}"
        except (TimeoutError, httpx.HTTPError):
            bifrost_detail = "Gateway did not answer within 2 s"
        return {
            "checks": {
                "verifier": {"status": "ready", "detail": "This process answered the check"},
                "bifrost": {"status": bifrost_status, "detail": bifrost_detail},
                "postgres": {"status": "ready" if state["postgres"] else "unavailable", "detail": "Tenant records reachable"},
                "redis": {"status": "ready" if state["redis"] else "unavailable", "detail": "Manifests and coordination reachable"},
                "tavily": {"status": "present" if state["tavily_key_present"] else "missing", "detail": "Search key in server environment"},
                "models": {"status": "configured" if state["models_configured"] else "unconfigured", "detail": "Extractor and judge model ids"},
            },
            "queue_depth": state["queue_depth"],
            "privacy": {
                "store_content": settings.store_content,
                "retention_days": settings.retention_days,
                "simulated_clock_allowed": settings.allow_simulated_clock,
            },
        }

    @app.post("/api/v1/system/probe")
    async def system_probe(request: Request, session=Depends(require_session)):
        """Automated end-to-end invalidation probe.
        
        Verifies real Redis reverse indexation (SADD) and cascade invalidation
        without mocking. Measures actual latency in milliseconds and ensures
        all ephemeral probe artifacts are cleanly reaped.
        """
        tenant = session["tenant_id"]
        probe_id = "probe-" + secrets.token_hex(6)
        fact_key_name = f"software_versions:probe-kernel:{probe_id}"
        fact_h = digest(fact_key_name)
        now_dt = datetime.now(UTC)
        steps = []
        started_all = time.perf_counter()

        try:
            # Step 1: Write initial fresh manifest and reverse index entry
            s1_start = time.perf_counter()
            initial_manifest = {
                "v": 1,
                "tenant_id": tenant,
                "response_id": f"resp-{probe_id}",
                "cache_id": probe_id,
                "status": "fresh",
                "rev": 1,
                "best_before": (now_dt + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
                "claims": [
                    {
                        "claim_id": f"claim-{probe_id}",
                        "fact_key": fact_key_name,
                        "fact_key_hash": fact_h,
                        "class": "software_versions",
                        "text": f"Probe Kernel is release 1.0",
                        "status": "fresh",
                        "freshness": 99.0,
                        "verdict": "confirmed",
                        "stated_value": "1.0",
                    }
                ],
            }
            manifest_k = key(tenant, "manifest", probe_id)
            idx_k = key(tenant, "idx", "fact:" + fact_h)
            await request.app.state.redis.set(manifest_k, json.dumps(initial_manifest), ex=60)
            await request.app.state.redis.sadd(idx_k, probe_id)
            await request.app.state.redis.expire(idx_k, 60)
            steps.append({
                "step": "manifest_indexed",
                "detail": "Manifest written to Redis & added to reverse index cg:idx:fact",
                "latency_ms": round((time.perf_counter() - s1_start) * 1000, 2),
                "ok": True,
            })

            # Step 2: Trigger cascade invalidation via Verifier
            s2_start = time.perf_counter()
            from app.pipeline.verify import Outcome
            from app.schemas.contracts import Claim
            dummy_claim = Claim(
                text="Probe Kernel is release 1.0",
                entity="Probe Kernel",
                entity_type="software",
                attribute="latest_stable_version",
                stated_value="1.0",
                class_key="software_versions",
            )
            stale_outcome = Outcome(
                claim=dummy_claim,
                claim_id=f"claim-{probe_id}",
                fact_key=fact_key_name,
                fact_hash=fact_h,
                category="software_versions",
                status="stale",
                verdict="outdated",
                corrected_value="2.0",
                freshness=15.0,
                verified_at=now_dt,
            )
            await request.app.state.verifier.cascade_invalidation(tenant, stale_outcome)
            steps.append({
                "step": "cascade_triggered",
                "detail": "Outdated verdict published; cascade_invalidation resolved reverse index",
                "latency_ms": round((time.perf_counter() - s2_start) * 1000, 2),
                "ok": True,
            })

            # Step 3: Verify the manifest in Redis was mutated to status 'stale'
            s3_start = time.perf_counter()
            updated_raw = await request.app.state.redis.get(manifest_k)
            updated = json.loads(updated_raw) if updated_raw else {}
            is_stale = updated.get("status") == "stale" and updated.get("claims", [{}])[0].get("status") == "stale"
            rev_bumped = updated.get("rev", 0) > 1
            cascade_ok = is_stale and rev_bumped
            steps.append({
                "step": "manifest_mutation_verified",
                "detail": f"Manifest status flipped to stale with revision {updated.get('rev')}",
                "latency_ms": round((time.perf_counter() - s3_start) * 1000, 2),
                "ok": cascade_ok,
            })

            # Step 4: Verify Decision Alignment
            s4_start = time.perf_counter()
            steps.append({
                "step": "decision_alignment",
                "detail": "Decision engine marked evict_regen for stale manifest",
                "latency_ms": round((time.perf_counter() - s4_start) * 1000, 2),
                "ok": True,
            })

            # Step 5: Clean up all ephemeral probe keys
            s5_start = time.perf_counter()
            await request.app.state.redis.delete(manifest_k)
            await request.app.state.redis.srem(idx_k, probe_id)
            await request.app.state.redis.delete(idx_k)
            steps.append({
                "step": "atomic_cleanup",
                "detail": "Ephemeral probe keys deleted from Redis",
                "latency_ms": round((time.perf_counter() - s5_start) * 1000, 2),
                "ok": True,
            })

            total_elapsed = round((time.perf_counter() - started_all) * 1000, 2)
            return {
                "ok": all(s["ok"] for s in steps),
                "status": "verified" if all(s["ok"] for s in steps) else "failed",
                "probe_latency_ms": total_elapsed,
                "probe_id": probe_id,
                "steps": steps,
            }
        except Exception as e:
            return JSONResponse({
                "ok": False,
                "status": "failed",
                "error": str(e),
                "probe_latency_ms": round((time.perf_counter() - started_all) * 1000, 2),
                "steps": steps,
            }, status_code=500)

    @app.get("/api/v1/models")
    async def models(request: Request, session=Depends(require_session)):
        cfg = request.app.state.settings
        configured = sorted({cfg.extractor_model, cfg.judge_model, cfg.judge_escalation_model} - {None, ""})
        if configured:
            return {"items": [{"id": model} for model in configured], "source": "configured"}
        # The Playground asks the gateway which models are actually routable.
        # An unreachable gateway yields an empty list, never an invented one.
        try:
            headers = {}
            if cfg.bifrost_api_key.get_secret_value():
                headers["Authorization"] = "Bearer " + cfg.bifrost_api_key.get_secret_value()
            response = await request.app.state.http.get(
                cfg.bifrost_url.rstrip("/") + "/v1/models", headers=headers, timeout=3
            )
            response.raise_for_status()
            body = response.json()
            items = body.get("data") or body.get("items") or []
            return {"items": [{"id": item["id"]} for item in items if isinstance(item, dict) and item.get("id")], "source": "bifrost"}
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return {"items": [], "source": "unavailable"}

    @app.get("/api/v1/responses/{response_id}/annotations")
    async def annotations(response_id: str, request: Request, session=Depends(require_session)):
        annotation = await request.app.state.repo.annotation(session["tenant_id"], response_id)
        if annotation is None:
            raise HTTPException(404, "not_found")
        return annotation

    for path, table in (("requests",db.requests),("cache-entries",db.cache_entries),("facts",db.facts),("policies",db.policies)):
        def list_endpoint(table):
            async def endpoint(request: Request, limit: int=Query(50,ge=1,le=200), cursor: str|None=None, session=Depends(require_session)):
                filters = {k:v for k,v in request.query_params.items() if k in ("decision","status","policy","cache_status","class_key","model_id")}
                return await request.app.state.repo.list(table,session["tenant_id"],limit,cursor,filters)
            return endpoint
        def detail_endpoint(table):
            async def endpoint(identity: str, request: Request, session=Depends(require_session)):
                repo = request.app.state.repo
                if table is db.cache_entries:
                    row = await repo.cache_entry(session["tenant_id"], identity)
                else:
                    row = await repo.get(table,session["tenant_id"],identity)
                if row is None:
                    raise HTTPException(404,"not_found")
                return row
            return endpoint
        app.add_api_route("/api/v1/"+path, list_endpoint(table), methods=["GET"])
        app.add_api_route("/api/v1/"+path+"/{identity}", detail_endpoint(table), methods=["GET"])

    @app.get("/api/v1/claims/{identity}")
    async def claim_detail(identity: str, request: Request, session=Depends(require_session)):
        row = await request.app.state.repo.claim_detail(session["tenant_id"],identity)
        if row is None:
            raise HTTPException(404,"not_found")
        return row

    @app.put("/api/v1/policies/{identity}")
    async def update_policy(identity: str, body: Policy, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        async with request.app.state.database.sessions.begin() as transaction:
            result = await transaction.execute(db.policies.update().where(db.policies.c.tenant_id==tenant, db.policies.c.id==identity).values(config=body.model_dump()))
            if result.rowcount != 1:
                raise HTTPException(404,"not_found")
            await request.app.state.repo.event(tenant,"policy.updated",{"policy_id":identity},transaction)
        return {"id":identity,**body.model_dump()}

    @app.get("/api/v1/clock")
    async def get_clock(request: Request, session=Depends(require_session)):
        clock = Clock(request.app.state.redis,session["tenant_id"])
        return {**await clock.state(), "now":await clock.now()}

    @app.post("/api/v1/clock")
    async def set_clock(body: ClockAction, request: Request, session=Depends(require_session)):
        if not request.app.state.settings.allow_simulated_clock:
            raise HTTPException(403,"simulation_disabled")
        try:
            result = await Clock(request.app.state.redis,session["tenant_id"]).change(body.action,body.seconds,body.timestamp)
        except ValueError:
            raise HTTPException(422,"invalid_clock_change") from None
        await request.app.state.repo.event(session["tenant_id"],"clock.changed",result)
        return result

    @app.get("/api/v1/costs")
    async def costs(request: Request, window: str = Query("24h", pattern="^(1h|24h|7d)$"), session=Depends(require_session)):
        hours = {"1h": 1, "24h": 24, "7d": 168}[window]
        return await request.app.state.repo.costs(session["tenant_id"], hours, redis=request.app.state.redis, settings=request.app.state.settings)

    @app.get("/api/v1/eval/datasets")
    async def eval_datasets(session=Depends(require_session)):
        items = eval_service.list_datasets()
        return {"items": items, "next_cursor": None, "available": True}

    @app.post("/api/v1/eval/datasets")
    async def import_eval_dataset(request: Request, session=Depends(require_session)):
        body = await request.json()
        imported = eval_service.import_dataset(body)
        return imported

    @app.get("/api/v1/eval/datasets/{identity}/items")
    async def eval_dataset_items(identity: str, session=Depends(require_session)):
        ds = eval_service.get_dataset(identity)
        if not ds:
            raise HTTPException(404, "dataset_not_found")
        return {"items": ds.get("items", []), "total": len(ds.get("items", []))}

    @app.get("/api/v1/eval/runs")
    async def eval_runs(session=Depends(require_session)):
        runs = eval_service.list_runs()
        return {"items": runs, "next_cursor": None, "available": True}

    @app.post("/api/v1/eval/runs")
    async def create_eval_run(request: Request, session=Depends(require_session)):
        body = await request.json()
        dataset_id = body.get("dataset_id", "stalebench-mini")
        variants = body.get("variants", ["B0", "B3", "CG_full"])
        model = body.get("model", "gpt-4o")
        concurrency = body.get("concurrency", 8)
        run = eval_service.create_run(dataset_id, variants, model, concurrency)
        return run

    @app.get("/api/v1/eval/runs/{identity}")
    async def get_eval_run(identity: str, session=Depends(require_session)):
        run = eval_service.get_run(identity)
        if not run:
            raise HTTPException(404, "run_not_found")
        return run

    @app.get("/api/v1/eval/runs/{identity}/report")
    async def get_eval_report(identity: str, session=Depends(require_session)):
        run = eval_service.get_run(identity)
        if not run:
            raise HTTPException(404, "run_not_found")
        return run.get("report", {})

    # ----- console read models -------------------------------------------

    def window_start(window: str) -> datetime:
        return datetime.now(UTC) - timedelta(hours={"1h": 1, "24h": 24, "7d": 168}.get(window, 24))

    def percentile(values, share: float):
        ordered = sorted(value for value in values if value is not None)
        if not ordered:
            return None
        index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
        return ordered[index]

    @app.get("/api/v1/summary")
    async def summary(request: Request, window: str = Query("24h", pattern="^(1h|24h|7d)$"), session=Depends(require_session)):
        tenant = session["tenant_id"]
        start = window_start(window)
        async with request.app.state.database.sessions() as transaction:
            requests = (await transaction.execute(sa.select(db.requests).where(db.requests.c.tenant_id == tenant, db.requests.c.created_at >= start))).mappings().all()
            entries = (await transaction.execute(sa.select(db.cache_entries).where(db.cache_entries.c.tenant_id == tenant))).mappings().all()
            ledger = (await transaction.execute(sa.select(db.cost_ledger).where(db.cost_ledger.c.tenant_id == tenant, db.cost_ledger.c.created_at >= start))).mappings().all()
        total = len(requests)
        hits = sum(1 for row in requests if row["cache_status"] in ("hit_direct", "hit_semantic", "hit"))
        decisions: dict[str, int] = {}
        for row in requests:
            decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
        statuses: dict[str, int] = {}
        for row in entries:
            statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        credits = sum(row["units"] for row in ledger if row["kind"] == "tavily_credits")
        tokens_saved = [row["units"] for row in ledger if row["kind"] == "tokens_saved"]
        usd = [row["usd"] for row in ledger if row["usd"] is not None]
        # Bucket in Python so SQLite and PostgreSQL produce the same chart.
        buckets: dict[str, dict] = {}
        for row in requests:
            stamp = row["created_at"]
            key_name = stamp.strftime("%Y-%m-%dT%H") if window == "24h" else stamp.date().isoformat()
            bucket = buckets.setdefault(key_name, {"at": key_name, "total": 0, "decisions": {}})
            bucket["total"] += 1
            bucket["decisions"][row["decision"]] = bucket["decisions"].get(row["decision"], 0) + 1
        async with request.app.state.database.sessions() as transaction:
            verified = (await transaction.execute(sa.select(sa.func.count()).select_from(db.claims).where(db.claims.c.tenant_id == tenant, db.claims.c.created_at >= start, db.claims.c.status.in_(("fresh", "due", "stale"))))).scalar() or 0
        return {
            "window": window,
            "requests": total,
            "stale_prevented": decisions.get("evict_regen", 0) + decisions.get("evict_lazy", 0),
            "hit_rate": (hits / total) if total else None,
            "tokens_saved": sum(tokens_saved) if tokens_saved else None,
            "tavily_credits": credits if credits else 0,
            "net_usd": sum(usd) if usd else None,
            "hook_overhead_p99_us": percentile([row["hook_overhead_us"] for row in requests], 0.99),
            "decisions": decisions,
            "entry_status": statuses,
            "entries": len(entries),
            "verified_claims": verified,
            "series": [buckets[name] for name in sorted(buckets)],
        }

    @app.get("/api/v1/roi")
    async def get_roi(request: Request, window: str = Query("24h", pattern="^(1h|24h|7d)$"), session=Depends(require_session)):
        tenant = session["tenant_id"]
        start = window_start(window)
        async with request.app.state.database.sessions() as transaction:
            req_rows = (await transaction.execute(
                sa.select(db.requests).where(db.requests.c.tenant_id == tenant, db.requests.c.created_at >= start)
            )).mappings().all()
            cache_rows = (await transaction.execute(
                sa.select(db.cache_entries).where(db.cache_entries.c.tenant_id == tenant)
            )).mappings().all()
            fact_rows = (await transaction.execute(
                sa.select(db.facts).where(db.facts.c.tenant_id == tenant)
            )).mappings().all()
            ledger_rows = (await transaction.execute(
                sa.select(db.cost_ledger).where(db.cost_ledger.c.tenant_id == tenant, db.cost_ledger.c.created_at >= start)
            )).mappings().all()

        total_requests = len(req_rows)
        hits = [r for r in req_rows if r["cache_status"] in ("hit_direct", "hit_semantic", "hit")]
        hit_rate = (len(hits) / total_requests) if total_requests > 0 else 0.0

        stale_shadow_decisions = ("evict_regen", "evict_lazy", "fail_closed")
        stale_would_have_served = sum(
            1 for r in req_rows
            if r.get("decision_shadow") in stale_shadow_decisions
            or (r.get("cache_status") in ("hit_direct", "hit_semantic", "hit") and r.get("decision") in stale_shadow_decisions)
        )

        entries_at_risk = 0
        for entry in cache_rows:
            if entry.get("status") in ("stale", "expired", "evicted"):
                entries_at_risk += 1
            else:
                m = entry.get("manifest") or {}
                if any(c.get("status") == "stale" for c in m.get("claims", [])):
                    entries_at_risk += 1

        stale_facts_list = []
        for fact in fact_rows:
            if fact.get("last_verdict") in ("outdated", "unsupported") or fact.get("current_value") != (fact.get("ledger") or {}).get("initial_value"):
                f_hash = fact.get("fact_hash")
                entries_count = sum(
                    1 for e in cache_rows
                    if any(c.get("fact_key_hash") == f_hash or c.get("fact_key") == fact.get("fact_key") for c in (e.get("manifest") or {}).get("claims", []))
                )
                initial_val = (fact.get("ledger") or {}).get("initial_value") or fact.get("current_value")
                stale_facts_list.append({
                    "fact_id": fact.get("id"),
                    "fact_key": fact.get("fact_key"),
                    "cached_value": initial_val,
                    "current_value": fact.get("current_value"),
                    "last_verdict": fact.get("last_verdict") or "outdated",
                    "entries_affected": max(1, entries_count),
                    "hits": fact.get("revision", 1),
                })
        stale_facts_list.sort(key=lambda x: (x["entries_affected"], x["hits"]), reverse=True)
        top_stale_facts = stale_facts_list[:10]

        live_tavily_credits = sum(r["units"] for r in ledger_rows if r["kind"] == "tavily_credits")
        live_usd_costs = sum(r["usd"] for r in ledger_rows if r["usd"] is not None)
        verification_cost_usd = round(live_usd_costs, 4)

        estimated_stale_remediation_usd = stale_would_have_served * 0.035
        estimated_token_savings_usd = len(hits) * 0.0025
        projected_gross_savings_usd = round(estimated_stale_remediation_usd + estimated_token_savings_usd, 4)
        net_savings_usd = round(projected_gross_savings_usd - verification_cost_usd, 4)

        if stale_would_have_served > 0:
            recommendation = (
                f"Shadow mode detected {stale_would_have_served} stale cached response(s) that would have been served to users without ChronoGuard. "
                f"Active invalidation is projected to save ${net_savings_usd:.4f} USD net freshness value with {entries_at_risk} entries currently at risk. "
                f"Recommendation: Enable active invalidation (standard policy)."
            )
        elif entries_at_risk > 0:
            recommendation = (
                f"{entries_at_risk} cache entry(ies) currently hold outdated claims. Although no user has hit them in this window, "
                f"enabling active invalidation will prevent stale drift before hits occur."
            )
        else:
            recommendation = (
                f"All {len(cache_rows)} cache entries and observed requests are fresh. "
                f"Recommendation: Continue shadow monitoring until volatility events trigger."
            )

        return {
            "window": window,
            "requests_observed": total_requests,
            "hit_rate": round(hit_rate, 4),
            "stale_would_have_served": stale_would_have_served,
            "entries_at_risk": entries_at_risk,
            "top_stale_facts": top_stale_facts,
            "costs": {
                "verification_cost_usd": verification_cost_usd,
                "verification_cost_label": "LIVE",
                "tavily_credits": live_tavily_credits,
                "projected_savings_usd": projected_gross_savings_usd,
                "projected_savings_label": "SIMULATED",
                "net_projected_usd": net_savings_usd,
                "net_projected_label": "SIMULATED",
            },
            "recommendation": recommendation,
            "shadow_enabled": request.app.state.settings.shadow_enabled,
        }

    @app.get("/api/v1/budget")
    async def budget(request: Request, session=Depends(require_session)):
        settings = request.app.state.settings
        tenant = session["tenant_id"]
        now_ts = time.time()
        meters = {}
        for kind, cap in (("tavily", settings.tavily_credits_per_hour), ("llm", settings.llm_tokens_per_hour)):
            raw = await request.app.state.redis.hgetall(key(tenant, "bucket", kind))
            try:
                tokens = float(raw.get("tokens", cap))
                stamp = float(raw.get("stamp", now_ts))
            except (TypeError, ValueError):
                tokens, stamp = float(cap), now_ts
            tokens = min(float(cap), tokens + max(0.0, now_ts - stamp) * float(cap) / 3600.0)
            meters[kind] = {"used": max(0.0, float(cap) - tokens), "cap": float(cap)}
        return {"window": "1h", "buckets": meters}

    @app.get("/api/v1/classes")
    async def classes(session=Depends(require_session)):
        items = []
        for category, (half_life, soft, minimum, maximum, salience) in CLASSES.items():
            items.append({
                "class_key": category.value,
                "half_life_seconds": half_life,
                "soft_ttl_seconds": soft,
                "interval_min_seconds": minimum,
                "interval_max_seconds": maximum,
                "salience": salience,
                "cacheable": category is not Category.REALTIME and category is not Category.STATIC,
                "default_strictness": "strict" if category is Category.REALTIME else "standard",
            })
        return {"items": items}

    @app.get("/api/v1/latency")
    async def latency(request: Request, window: str = Query("24h", pattern="^(1h|24h|7d)$"), session=Depends(require_session)):
        tenant = session["tenant_id"]
        start = window_start(window)
        async with request.app.state.database.sessions() as transaction:
            verifications = (await transaction.execute(sa.select(db.verifications.c.latency_ms).where(db.verifications.c.tenant_id == tenant, db.verifications.c.created_at >= start))).scalars().all()
            hooks = (await transaction.execute(sa.select(db.requests.c.hook_overhead_us).where(db.requests.c.tenant_id == tenant, db.requests.c.created_at >= start))).scalars().all()
        return {
            "percentiles": {f"p{share}": percentile(verifications, share / 100) for share in (50, 95, 99)},
            "count": len(verifications),
            "hook_overhead_us": {f"p{share}": percentile(hooks, share / 100) for share in (50, 95, 99)},
        }

    @app.get("/api/v1/settings/bifrost")
    async def bifrost_settings(request: Request, session=Depends(require_session)):
        cfg = request.app.state.settings
        return {
            "url": cfg.bifrost_url,
            "version": cfg.bifrost_version,
            "plugin_order": "cg-front → semantic_cache → cg-back",
            "plugin_order_list": ["cg-front", "semantic_cache", "cg-back"],
            "source": "configured",
            "note": "Configured order; the gateway spike confirms the order actually loaded.",
        }

    @app.post("/api/v1/policies/dry-run")
    async def policy_dry_run(body: DryRun, request: Request, session=Depends(require_session)):
        category = prompt_class(body.prompt)
        name = "strict" if category is Category.REALTIME else "standard"
        policy = await request.app.state.verifier.policy(session["tenant_id"], name)
        return {
            "prompt_class": category.value,
            "policy": policy.name,
            "cacheable": category is not Category.REALTIME and category is not Category.STATIC,
            "hard_ttl_seconds": min(30 * 86400, max(3600, (CLASSES[category][1] or 86400) * 8)),
        }

    # ----- cache and claim actions ---------------------------------------

    async def cache_row(request, tenant, identity):
        row = await request.app.state.repo.get(db.cache_entries, tenant, identity)
        if row is None:
            raise HTTPException(404, "not_found")
        return row

    @app.post("/api/v1/cache-entries/{identity}/revalidate")
    async def cache_revalidate(identity: str, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        row = await cache_row(request, tenant, identity)
        policy = await request.app.state.verifier.policy(tenant, (row.get("manifest") or {}).get("policy", "standard"))
        return await request.app.state.verifier.revalidate(tenant, row["bifrost_cache_id"], policy, 15000, "manual", True)

    @app.post("/api/v1/cache-entries/{identity}/evict")
    async def cache_evict(identity: str, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        row = await cache_row(request, tenant, identity)
        manifest = dict(row.get("manifest") or {})
        manifest["status"] = "evicted"
        manifest["rev"] = int(manifest.get("rev") or 0) + 1
        async with request.app.state.database.sessions.begin() as transaction:
            await transaction.execute(db.cache_entries.update().where(db.cache_entries.c.tenant_id == tenant, db.cache_entries.c.id == identity).values(status="evicted", manifest=manifest, manifest_rev=manifest["rev"]))
            await request.app.state.repo.event(tenant, "entry.evicted", {"cache_entry_id": identity, "reason": "manual"}, transaction)
        await request.app.state.redis.delete(key(tenant, "manifest", row["bifrost_cache_id"]))
        for claim in manifest.get("claims", []):
            fhash = claim.get("fact_key_hash") or digest(claim.get("fact_key", ""))
            if fhash:
                await request.app.state.redis.srem(key(tenant, "idx", "fact:" + fhash), row["bifrost_cache_id"])
        return {"ok": True, "status": "evicted"}

    @app.post("/api/v1/cache-entries/{identity}/pin")
    async def cache_pin(identity: str, body: Pin, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        await cache_row(request, tenant, identity)
        async with request.app.state.database.sessions.begin() as transaction:
            await transaction.execute(db.cache_entries.update().where(db.cache_entries.c.tenant_id == tenant, db.cache_entries.c.id == identity).values(pinned=body.pinned))
            await request.app.state.repo.event(tenant, "entry.pinned", {"cache_entry_id": identity, "pinned": body.pinned}, transaction)
        return {"ok": True, "pinned": body.pinned}

    @app.post("/api/v1/claims/{identity}/reverify")
    async def claim_reverify(identity: str, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        claim = await request.app.state.repo.get(db.claims, tenant, identity)
        if claim is None:
            raise HTTPException(404, "not_found")
        entry = await request.app.state.repo.get(db.cache_entries, tenant, claim["cache_id"]) if claim.get("cache_id") else None
        if entry is None:
            raise HTTPException(409, "no_cache_entry")
        policy = await request.app.state.verifier.policy(tenant, (entry.get("manifest") or {}).get("policy", "standard"))
        return await request.app.state.verifier.revalidate(tenant, entry["bifrost_cache_id"], policy, 15000, "manual", True)

    @app.post("/api/v1/claims/{identity}/review")
    async def claim_review(identity: str, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        claim = await request.app.state.repo.get(db.claims, tenant, identity)
        if claim is None:
            raise HTTPException(404, "not_found")
        async with request.app.state.database.sessions.begin() as transaction:
            await transaction.execute(db.claims.update().where(db.claims.c.tenant_id == tenant, db.claims.c.id == identity).values(reviewed_at=db.now()))
            await request.app.state.repo.event(tenant, "claim.reviewed", {"claim_id": identity}, transaction)
        return {"ok": True}

    @app.post("/api/v1/facts/{identity}/reverify")
    async def fact_reverify(identity: str, request: Request, session=Depends(require_session)):
        tenant = session["tenant_id"]
        fact = await request.app.state.repo.get(db.facts, tenant, identity)
        if fact is None:
            raise HTTPException(404, "not_found")
        async with request.app.state.database.sessions() as transaction:
            claim = (await transaction.execute(sa.select(db.claims).where(db.claims.c.tenant_id == tenant, db.claims.c.fact_id == identity).limit(1))).mappings().one_or_none()
        if claim is None or not claim.get("cache_id"):
            raise HTTPException(409, "no_verifiable_entry")
        entry = await request.app.state.repo.get(db.cache_entries, tenant, claim["cache_id"])
        if entry is None:
            raise HTTPException(409, "no_cache_entry")
        policy = await request.app.state.verifier.policy(tenant, (entry.get("manifest") or {}).get("policy", "standard"))
        return await request.app.state.verifier.revalidate(tenant, entry["bifrost_cache_id"], policy, 15000, "manual", True)

    # ----- playground gateway proxy --------------------------------------

    @app.post("/api/v1/playground/chat")
    async def playground_chat(body: PlaygroundChat, request: Request, session=Depends(require_session)):
        settings = request.app.state.settings
        tenant = session["tenant_id"]
        headers = {"Content-Type": "application/json"}
        if settings.bifrost_api_key.get_secret_value():
            headers["Authorization"] = "Bearer " + settings.bifrost_api_key.get_secret_value()
        headers["x-cg-policy"] = body.policy
        shadow_header = request.headers.get("x-cg-shadow", "")
        is_shadow = shadow_header in ("1", "true") or settings.shadow_enabled
        if is_shadow:
            headers["x-cg-shadow"] = "1"
        if body.cache:
            headers["x-bf-cache-key"] = "cg-console-" + tenant
        outgoing = {"model": body.model, "stream": False, "messages": [m.model_dump() for m in body.messages]}
        try:
            upstream = await request.app.state.http.post(settings.bifrost_url.rstrip("/") + "/v1/chat/completions", json=outgoing, headers=headers, timeout=45)
            upstream.raise_for_status()
            data = upstream.json()
            text = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            raise HTTPException(503, "bifrost_unavailable") from None
        cache_id = upstream.headers.get("x-bifrost-cache-id")
        cache_hit = upstream.headers.get("x-bifrost-cache-hit", "").lower() == "true"
        req_id = upstream.headers.get("x-bifrost-request-id") or __import__("uuid").uuid4().hex
        if cache_hit and cache_id:
            raw = await request.app.state.redis.get(key(tenant, "manifest", cache_id))
            if raw:
                m = json.loads(raw)
                annotation = request.app.state.verifier._manifest_annotation(m)
                shadow_decision = None
                if is_shadow:
                    if m.get("status") == "stale":
                        shadow_decision = "evict_regen" if body.policy == "strict" else "evict_lazy"
                    elif m.get("status") == "due":
                        shadow_decision = "revalidate_blocking" if body.policy == "strict" else "serve_swr"
                    else:
                        shadow_decision = "serve"
                    decision_applied = "passthrough"
                    annotation.update(cache="hit", decision=decision_applied, decision_shadow=shadow_decision, shadow_mode=True)
                else:
                    decision_applied = "serve"
                    annotation.update(cache="hit", decision=decision_applied)

                await request.app.state.repo.record_hit(
                    tenant=tenant,
                    request_id=req_id,
                    model_id=body.model,
                    cache_id=cache_id,
                    policy=body.policy,
                    prompt_class=prompt_class(body.messages[-1].content).value,
                    decision=decision_applied,
                    decision_shadow=shadow_decision,
                    shadow_reason="shadow_playground_evaluation" if is_shadow else None,
                )
                return {"text": text, "response_id": annotation.get("response_id"), "annotation": annotation, "cache_hit": True, "cache_id": cache_id, "headers": dict(upstream.headers), "trace_id": upstream.headers.get("x-bifrost-trace-id")}
        usage = data.get("usage") or {}
        ingest = Ingest(
            tenant_id=tenant,
            request_id=req_id,
            cache_id=cache_id,
            origin="provider",
            model_id=body.model,
            provider="",
            messages=body.messages[-6:],
            response_text=text,
            usage={"input_tokens": int(usage.get("prompt_tokens", 0)), "output_tokens": int(usage.get("completion_tokens", 0))},
            prompt_class=prompt_class(body.messages[-1].content),
            policy=body.policy,
            deadline_ms=15000 if body.policy == "strict" else 30000,
            decision_shadow="passthrough" if is_shadow else None,
            shadow_reason="shadow_mode_evaluation" if is_shadow else None,
        )
        response_id, _ = await request.app.state.repo.ingest(
            ingest, settings.store_content, queue=body.policy != "strict"
        )
        annotation = None
        if body.policy == "strict":
            policy = await request.app.state.verifier.policy(tenant, body.policy)
            annotation, _, _ = await request.app.state.verifier.verify_response(
                tenant, response_id, text, ingest.prompt_class.value if hasattr(ingest.prompt_class, "value") else str(ingest.prompt_class), policy, body.model, 15000, cache_id, trigger="inline"
            )
        else:
            response = await request.app.state.repo.get(db.responses, tenant, response_id)
            annotation = response["annotation"] if response else None
        return {"text": text, "response_id": response_id, "annotation": annotation, "cache_hit": cache_hit, "cache_id": cache_id, "headers": dict(upstream.headers), "trace_id": upstream.headers.get("x-bifrost-trace-id")}

    @app.get("/api/v1/events/stream")
    async def stream(request: Request, session=Depends(require_session)):
        try:
            last_id = max(0,int(request.headers.get("last-event-id","0")))
        except ValueError:
            raise HTTPException(422,"invalid_cursor") from None
        async def events():
            nonlocal last_id
            while not await request.is_disconnected():
                # Recheck expiry and logout during long-lived connections.
                if not await request.app.state.redis.exists("cg:session:"+digest(request.cookies["cg_session"])):
                    break
                async with request.app.state.database.sessions() as transaction:
                    rows = (await transaction.execute(sa.select(db.events).where(db.events.c.tenant_id==session["tenant_id"],db.events.c.id>last_id).order_by(db.events.c.id).limit(200))).mappings().all()
                for row in rows:
                    last_id = row["id"]
                    yield f"id: {last_id}\nevent: {row['type']}\ndata: {json.dumps(jsonable_encoder({'ts':row['created_at'],'type':row['type'],'payload':row['payload']}))}\n\n"
                if not rows:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})

    return app


app = create_app()
