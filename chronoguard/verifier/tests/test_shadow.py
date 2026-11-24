import json
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import fakeredis.aioredis
from app import db
from app.config import Settings
from app.main import create_app
from app.security import digest, session_key

INTERNAL_KEY = "k" * 40

@pytest.fixture
async def shadow_client(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'verifier_shadow.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(db.metadata.create_all)
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite://"),
        redis_url=SecretStr("redis://localhost:6379/0"),
        internal_key=SecretStr(INTERNAL_KEY),
        session_secret=SecretStr("s" * 40),
        admin_password_hash=SecretStr("$argon2id$v=19$m=65536,t=3,p=4$fake$hash"),
        console_origin="http://localhost:3000",
        allow_simulated_clock=True,
        shadow_enabled=True,
    )
    application = create_app(settings=settings, database=database, redis_client=redis_client)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
            yield c, redis_client, database


@pytest.mark.asyncio
async def test_record_hit_endpoint(shadow_client):
    c, _, _ = shadow_client
    payload = {
        "tenant_id": "default",
        "request_id": "req-hit-1",
        "cache_id": "cache-hit-1",
        "origin": "legacy_cache",
        "model_id": "gpt-4o",
        "policy": "standard",
        "prompt_class": "software_versions",
        "cache_status": "hit",
        "decision": "passthrough",
        "decision_shadow": "evict_regen",
        "shadow_reason": "shadow_mode_evaluation",
        "latency_ms": 2,
    }
    # Unauthenticated should fail
    resp = await c.post("/internal/v1/record-hit", json=payload)
    assert resp.status_code == 401

    # Authenticated with internal key should succeed
    resp = await c.post(
        "/internal/v1/record-hit",
        json=payload,
        headers={"x-cg-internal-key": INTERNAL_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["request_id"] is not None


@pytest.mark.asyncio
async def test_ingest_with_shadow_fields(shadow_client):
    c, _, database = shadow_client
    payload = {
        "tenant_id": "default",
        "request_id": "req-ingest-shadow-1",
        "origin": "provider",
        "model_id": "gpt-4o",
        "provider": "openai",
        "messages": [{"role": "user", "content": "What is Python 3.14?"}],
        "response_text": "Python 3.14 was released.",
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "prompt_class": "software_versions",
        "policy": "standard",
        "decision_shadow": "passthrough",
        "shadow_reason": "shadow_mode_evaluation",
    }
    resp = await c.post(
        "/internal/v1/ingest",
        json=payload,
        headers={"x-cg-internal-key": INTERNAL_KEY},
    )
    assert resp.status_code == 202
    res_id = resp.json()["response_id"]
    assert res_id is not None

    # Verify shadow fields were stored in db.requests
    async with database.sessions() as session:
        import sqlalchemy as sa
        row = (
            await session.execute(
                sa.select(db.requests).where(db.requests.c.bifrost_request_id == "req-ingest-shadow-1")
            )
        ).mappings().one()
        assert row["decision_shadow"] == "passthrough"
        assert row["shadow_reason"] == "shadow_mode_evaluation"


@pytest.mark.asyncio
async def test_roi_endpoint_comprehensive(shadow_client):
    c, redis_client, database = shadow_client

    # 1. Authenticate console session
    session_id = "test-session-roi"
    session_data = json.dumps({"tenant_id": "default", "csrf_token": "csrf-roi", "authenticated": True})
    await redis_client.set(session_key(c._transport.app.state.settings, session_id), session_data)
    c.cookies.set("cg_session", session_id)

    # 2. Record 3 requests:
    #    - Request 1: cache hit, shadow decision "evict_regen" (stale served in shadow)
    #    - Request 2: cache hit, shadow decision "serve" (fresh hit)
    #    - Request 3: cache miss, passthrough
    headers = {"x-cg-internal-key": INTERNAL_KEY}
    await c.post(
        "/internal/v1/record-hit",
        json={
            "tenant_id": "default",
            "request_id": "roi-req-1",
            "cache_id": "c-stale",
            "decision": "passthrough",
            "decision_shadow": "evict_regen",
            "shadow_reason": "known_stale",
            "prompt_class": "software_versions",
        },
        headers=headers,
    )
    await c.post(
        "/internal/v1/record-hit",
        json={
            "tenant_id": "default",
            "request_id": "roi-req-2",
            "cache_id": "c-fresh",
            "decision": "passthrough",
            "decision_shadow": "serve",
            "shadow_reason": "shadow_eval",
            "prompt_class": "software_versions",
        },
        headers=headers,
    )
    await c.post(
        "/internal/v1/ingest",
        json={
            "tenant_id": "default",
            "request_id": "roi-req-3",
            "model_id": "gpt-4o",
            "response_text": "Miss content",
            "prompt_class": "software_versions",
            "policy": "standard",
        },
        headers=headers,
    )

    # 3. Seed a stale cache entry and fact
    fact_key = "sw:node:version"
    fact_h = digest(fact_key)
    async with database.sessions.begin() as session:
        await session.execute(
            db.facts.insert().values(
                id="f1",
                tenant_id="default",
                fact_key=fact_key,
                fact_hash=fact_h,
                class_key="software_versions",
                entity="Node.js",
                attribute="version",
                current_value="v24.0.0",
                last_verdict="outdated",
                revision=3,
                ledger={"initial_value": "v20.0.0"},
            )
        )
        await session.execute(
            db.cache_entries.insert().values(
                id="ce1",
                tenant_id="default",
                bifrost_cache_id="c-stale",
                status="stale",
                manifest={
                    "status": "stale",
                    "claims": [
                        {"fact_key": fact_key, "fact_key_hash": fact_h, "status": "stale"}
                    ],
                },
            )
        )

    # 4. Fetch ROI report
    resp = await c.get("/api/v1/roi?window=24h")
    assert resp.status_code == 200
    roi = resp.json()

    assert roi["window"] == "24h"
    assert roi["requests_observed"] >= 3
    assert roi["stale_would_have_served"] == 1
    assert roi["entries_at_risk"] >= 1
    assert len(roi["top_stale_facts"]) >= 1

    top_fact = roi["top_stale_facts"][0]
    assert top_fact["fact_key"] == fact_key
    assert top_fact["cached_value"] == "v20.0.0"
    assert top_fact["current_value"] == "v24.0.0"
    assert top_fact["last_verdict"] == "outdated"

    assert roi["blocked_hits"] == 0
    assert roi["repaired_hits"] == 0
    assert roi["costs"]["verification_cost_usd"] is None
    assert roi["costs"]["verification_cost_label"] == "unpriced"
