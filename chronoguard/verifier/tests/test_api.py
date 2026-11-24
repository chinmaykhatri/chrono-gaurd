import json
import secrets
from argon2 import PasswordHasher
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import fakeredis.aioredis
from app import db
from app.config import Settings
from app.main import create_app
from app.security import digest, session_key

@pytest.fixture
async def client(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'verifier_api.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(db.metadata.create_all)
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite://"),
        redis_url=SecretStr("redis://localhost:6379/0"),
        internal_key=SecretStr("k" * 40),
        session_secret=SecretStr("s" * 40),
        admin_password_hash=SecretStr("$argon2id$v=19$m=65536,t=3,p=4$fake$hash"),
        console_origin="http://localhost:3000",
        allow_simulated_clock=True,
    )
    application = create_app(settings=settings, database=database, redis_client=redis_client)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
            yield c, redis_client, database

def test_net_savings_requires_prices_for_both_saved_and_spent_work():
    from app.repository import ledger_totals
    rows = [{"kind": "tokens_saved", "usd": 3}, {"kind": "llm_tokens", "usd": 5}]
    assert ledger_totals(rows)["net_usd"] == -2
    assert ledger_totals(rows[1:])["net_usd"] is None
    assert ledger_totals([*rows, {"kind": "tavily_credits", "usd": None}])["net_usd"] is None


@pytest.mark.asyncio
async def test_healthz(client):
    c, _, _ = client
    resp = await c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

@pytest.mark.asyncio
async def test_readyz(client):
    c, _, _ = client
    resp = await c.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "postgres" in resp.json()
    assert "redis" in resp.json()

@pytest.mark.asyncio
async def test_eval_datasets_and_runs(client):
    c, redis_client, _ = client
    # Seed authenticated session
    session_id = "test-session-123"
    session_data = json.dumps({"tenant_id": "default", "csrf_token": "csrf-token-123", "authenticated": True})
    await redis_client.set(session_key(c._transport.app.state.settings, session_id), session_data)
    c.cookies.set("cg_session", session_id)

    # GET /eval/datasets
    resp = await c.get("/api/v1/eval/datasets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert len(body["items"]) >= 1
    assert body["items"][0]["id"] == "stalebench-mini"

    resp = await c.get("/api/v1/eval/runs")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    csrf = {"Origin": "http://localhost:3000", "X-CSRF-Token": "csrf-token-123"}
    unsupported = await c.post("/api/v1/eval/runs", json={"dataset_id": "stalebench-mini"}, headers=csrf)
    assert unsupported.status_code == 422
    run = await c.post("/api/v1/eval/runs", json={"dataset_id": "release-replay"}, headers=csrf)
    assert run.status_code == 200
    run_id = run.json()["id"]
    resp = await c.get(f"/api/v1/eval/runs/{run_id}/report")
    assert resp.status_code == 200
    report = resp.json()
    assert report["status"] == "complete"
    assert report["provenance"] == "controlled_replay"
    assert all("credits" in row for row in report["rows"])
    assert len(report["variants"]) == 8

@pytest.mark.asyncio
async def test_classes_and_summary(client):
    c, redis_client, _ = client
    session_id = "test-session-456"
    session_data = json.dumps({"tenant_id": "default", "csrf_token": "csrf-token-456", "authenticated": True})
    await redis_client.set(session_key(c._transport.app.state.settings, session_id), session_data)
    c.cookies.set("cg_session", session_id)

    # Classes
    resp = await c.get("/api/v1/classes")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 8  # 8 volatility classes

    # Summary
    resp = await c.get("/api/v1/summary?window=24h")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["window"] == "24h"
    assert "requests" in summary
    assert "decisions" in summary

@pytest.mark.asyncio
async def test_clock_endpoints(client):
    c, redis_client, _ = client
    session_id = "test-session-789"
    csrf_token = "csrf-token-789"
    session_data = json.dumps({"tenant_id": "default", "csrf_token": csrf_token, "authenticated": True})
    await redis_client.set(session_key(c._transport.app.state.settings, session_id), session_data)
    c.cookies.set("cg_session", session_id)

    # Read clock
    resp = await c.get("/api/v1/clock")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "real"

    headers = {"origin": "http://localhost:3000", "x-csrf-token": csrf_token}

    # Advance clock by 1 day
    resp = await c.post("/api/v1/clock", json={"action": "advance", "seconds": 86400}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "simulated"
    assert resp.json()["offset_seconds"] == 86400

    # Reset clock
    resp = await c.post("/api/v1/clock", json={"action": "reset", "seconds": 0}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "real"

@pytest.mark.asyncio
async def test_system_probe(client):
    c, redis_client, _ = client
    session_id = "test-session-probe"
    csrf_token = "csrf-token-probe"
    session_data = json.dumps({"tenant_id": "default", "csrf_token": csrf_token, "authenticated": True})
    await redis_client.set(session_key(c._transport.app.state.settings, session_id), session_data)
    c.cookies.set("cg_session", session_id)

    headers = {"origin": "http://localhost:3000", "x-csrf-token": csrf_token}
    resp = await c.post("/api/v1/system/probe", json={}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "verified"
    assert data["probe_latency_ms"] >= 0
    assert data["provenance"] == "isolated_redis_probe"
    assert len(data["steps"]) == 4
    assert all(s["ok"] for s in data["steps"])

@pytest.mark.asyncio
async def test_operator_authentication_origin_csrf_and_tenant(client):
    c, redis, _ = client
    cfg = c._transport.app.state.settings
    password = secrets.token_urlsafe(20)
    cfg.admin_password_hash = SecretStr(PasswordHasher().hash(password))
    origin = {"origin": cfg.console_origin}
    assert (await c.get("/api/v1/auth/session")).status_code == 401
    assert (await c.get("/api/v1/facts")).status_code == 401
    assert await redis.keys("cg:operator:*") == []
    assert (await c.post("/api/v1/auth/login", json={"password": ""}, headers=origin)).status_code == 422
    assert (await c.post("/api/v1/auth/login", json={"password": "invalid"}, headers=origin)).status_code == 401
    assert (await c.post("/api/v1/auth/login", json={"password": password})).status_code == 403
    login = await c.post("/api/v1/auth/login", json={"password": password}, headers=origin)
    assert login.status_code == 200
    token = c.cookies["cg_session"]
    csrf = {"x-csrf-token": login.json()["csrf_token"]}
    assert "httponly" in login.headers["set-cookie"].lower()
    assert (await c.get("/api/v1/auth/session")).status_code == 200
    for headers in (origin, csrf, {**csrf, "origin": "https://example.org"}):
        assert (await c.post("/api/v1/auth/logout", headers=headers)).status_code == 403
    preflight = await c.options("/api/v1/auth/session", headers={"origin": "https://example.org",
                                "access-control-request-method": "GET"})
    assert "access-control-allow-origin" not in preflight.headers
    assert (await c.get("/internal/v1/health")).status_code == 401
    assert (await c.post("/api/v1/auth/logout", headers={**origin, **csrf})).status_code == 200
    c.cookies.set("cg_session", token)
    assert (await c.get("/api/v1/auth/session")).status_code == 401
    await redis.set("cg:session:" + digest(token), json.dumps(login.json()))
    assert (await c.get("/api/v1/auth/session")).status_code == 401
    await redis.set(session_key(cfg, token), json.dumps({**login.json(), "tenant_id":"other"}))
    assert (await c.get("/api/v1/facts")).status_code == 401
    await redis.set(session_key(cfg, token), json.dumps(login.json()))
    cfg.session_secret = SecretStr(secrets.token_urlsafe(40))
    assert (await c.get("/api/v1/auth/session")).status_code == 401


@pytest.mark.asyncio
async def test_login_attempts_expire_and_throttle(client):
    c, redis, _ = client
    cfg = c._transport.app.state.settings
    cfg.admin_password_hash = SecretStr(PasswordHasher().hash(secrets.token_urlsafe(20)))
    for _ in range(10):
        assert (await c.post("/api/v1/auth/login", json={"password":"invalid"},
                             headers={"origin":cfg.console_origin})).status_code == 401
    assert (await c.post("/api/v1/auth/login", json={"password":"invalid"},
                         headers={"origin":cfg.console_origin})).status_code == 429
    assert 0 < await redis.ttl((await redis.keys("cg:login:*"))[0]) <= 60
