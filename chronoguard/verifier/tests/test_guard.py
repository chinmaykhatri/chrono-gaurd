import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import fakeredis.aioredis

from app import db
from app.config import Settings
from app.main import create_app

INTERNAL_KEY = "k" * 40


@pytest.fixture
async def guard_client(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'verifier_guard.db'}")
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
        guard_enabled=True,
    )
    application = create_app(settings=settings, database=database, redis_client=redis_client)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
            yield c, redis_client, database


@pytest.mark.asyncio
async def test_guard_record_hit(guard_client):
    client, _, _ = guard_client
    # 1. Record a semantic hit where guard tripped
    resp = await client.post(
        "/internal/v1/record-hit",
        headers={"x-cg-internal-key": INTERNAL_KEY},
        json={
            "tenant_id": "default",
            "request_id": "req-guard-test-1",
            "cache_id": "cache-apple-ceo",
            "origin": "guard_bypassed",
            "model_id": "gpt-4o",
            "policy": "standard",
            "prompt_class": "org_people",
            "cache_status": "hit",
            "decision": "guard_bypass",
            "guard_tripped": True,
            "guard_reason": "year_mismatch",
            "query_signature": "num:2010|ent:apple|rel:ceo",
            "latency_ms": 2,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 2. Record a normal hit where guard passed
    resp2 = await client.post(
        "/internal/v1/record-hit",
        headers={"x-cg-internal-key": INTERNAL_KEY},
        json={
            "tenant_id": "default",
            "request_id": "req-guard-test-2",
            "cache_id": "cache-australia-cap",
            "origin": "legacy_cache",
            "model_id": "gpt-4o",
            "policy": "standard",
            "prompt_class": "slow_facts",
            "cache_status": "hit",
            "decision": "serve",
            "guard_tripped": False,
            "query_signature": "ent:australia|rel:capital",
            "latency_ms": 1,
        },
    )
    assert resp2.status_code == 200


def test_guard_eval_report_file():
    report_path = Path(__file__).resolve().parent.parent.parent / "eval" / "reports" / "guard-eval.json"
    assert report_path.exists(), "guard-eval.json must exist"

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["provenance"] == "LIVE"
    assert data["total_pairs"] == 60
    assert data["near_miss_count"] == 30
    assert data["paraphrase_count"] == 30
    assert data["accuracy"] >= 0.90
    assert data["precision"] >= 0.90
    assert data["recall"] >= 0.90
    assert data["budget_compliant_under_100us"] is True
    assert data["avg_total_overhead_us"] < 100.0
