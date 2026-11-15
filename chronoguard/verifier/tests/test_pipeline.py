import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app import db
from app.config import Settings
from app.main import create_app
from app.schemas.contracts import Category, Claim, Evidence, Verdict
from app.security import key


def make_claim(text, claim_text, entity, attribute, stated, klass=Category.SOFTWARE):
    start = text.index(claim_text)
    return Claim(
        text=claim_text,
        span=(start, start + len(claim_text)),
        entity=entity,
        entity_type="software",
        attribute=attribute,
        stated_value=stated,
        class_key=klass,
        importance=1.0,
    )


def make_evidence(identity, url, tier=1, snippet="Current release information."):
    return Evidence(
        id=identity,
        url=url,
        domain=urlsplit(url).hostname,
        title="Release information",
        snippet=snippet,
        retrieved_at=datetime.now(timezone.utc),
        tier=tier,
    )


class FakeModels:
    def __init__(self, claims, verdict):
        self.claims = claims
        self.verdict = verdict
        self.extracted = 0

    async def extract(self, text):
        self.extracted += 1
        return self.claims, {"input_tokens": 10, "output_tokens": 10}

    async def judge(self, claim, evidence):
        return self.verdict, {"input_tokens": 20, "output_tokens": 5}


class FakeTavily:
    def __init__(self, evidence, delay=0.0):
        self.evidence = evidence
        self.calls = 0
        self.delay = delay

    async def search(self, claim, depth="basic"):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.evidence, {"credits": 2.0}


def body(request_id, cache_id, text, policy="strict", prompt_class="software_versions"):
    return {
        "tenant_id": "default",
        "request_id": request_id,
        "cache_id": cache_id,
        "origin": "provider",
        "model_id": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "Which release should I use?"}],
        "response_text": text,
        "usage": {"input_tokens": 12, "output_tokens": 24},
        "prompt_class": prompt_class,
        "policy": policy,
        "deadline_ms": 4500,
    }


@pytest.fixture
async def app(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'verifier.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(db.metadata.create_all)
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite://"),
        redis_url=SecretStr("redis://localhost:6379/0"),
        internal_key=SecretStr("i" * 40),
        session_secret=SecretStr("s" * 40),
        admin_password_hash=SecretStr("$argon2id$v=19$m=65536,t=3,p=4$fake$hash"),
        console_origin="http://localhost:3000",
        tenant_id="default",
        allow_simulated_clock=True,
    )
    application = create_app(settings=settings, database=database, redis_client=redis_client)
    async with application.router.lifespan_context(application):
        yield application


async def call(app, path, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=payload, headers={"x-cg-internal-key": "i" * 40})


@pytest.mark.asyncio
async def test_verified_claim_is_persisted_and_reused_from_the_ledger(app):
    text = "Node.js 22 is the latest LTS release."
    claim = make_claim(text, "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    evidence = [
        make_evidence("e1", "https://nodejs.org/en/about/previous-releases", 1),
        make_evidence("e2", "https://github.com/nodejs/release", 2),
    ]
    models = FakeModels([claim], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1", "e2"]))
    tavily = FakeTavily(evidence)
    app.state.models = models
    app.state.tavily = tavily
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    response = await call(app, "/internal/v1/verify-inline", body("r1", "cache-alpha", text))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["annotation"]["claims"][0]["status"] == "fresh"
    assert payload["annotation"]["claims"][0]["freshness"] >= 80

    manifest = json.loads(await app.state.redis.get(key("default", "manifest", "cache-alpha")))
    assert manifest["v"] == 1
    assert manifest["status"] == "fresh"
    assert manifest["claims"][0]["fact_key"].startswith("software_versions:node-js:")
    assert tavily.calls == 1

    second = await call(app, "/internal/v1/verify-inline", body("r2", "cache-alpha", text))
    assert second.json()["annotation"]["claims"][0]["verdict"] == "confirmed"
    assert tavily.calls == 1

    async with app.state.database.sessions() as session:
        entries = (await session.execute(db.cache_entries.select())).mappings().all()
        claims = (await session.execute(db.claims.select())).mappings().all()
    assert len(entries) == 1
    assert entries[0]["bifrost_cache_id"] == "cache-alpha"
    assert len(claims) == 2


@pytest.mark.asyncio
async def test_unmet_evidence_rule_preserves_uncertainty(app):
    text = "Acme Cloud costs $99 per month."
    claim = make_claim(text, "Acme Cloud costs $99 per month", "Acme Cloud", "price_per_month", "$99 per month", Category.PRICING)
    evidence = [make_evidence("e1", "https://blog.example.net/acme-pricing", 3)]
    models = FakeModels(
        [claim],
        Verdict(
            verdict="outdated",
            confidence=0.93,
            corrected_value="$79 per month",
            contradict_ids=["e1"],
            rationale="A newer price is listed.",
        ),
    )
    tavily = FakeTavily(evidence)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    payload = (await call(app, "/internal/v1/verify-inline", body("r3", "cache-beta", text, prompt_class="pricing_plans"))).json()
    result = payload["annotation"]["claims"][0]
    assert result["status"] == "unverifiable"
    assert result["verdict"] == "unverifiable"
    assert result["freshness"] is None
    assert result["corrected_value"] is None


@pytest.mark.asyncio
async def test_exhausted_budget_never_becomes_fresh(app):
    text = "Rust 1.90 is the current stable release."
    claim = make_claim(text, "Rust 1.90 is the current stable release", "Rust", "latest_stable_version", "1.90")
    models = FakeModels([claim], Verdict(verdict="confirmed", confidence=0.9, support_ids=["e1"]))
    tavily = FakeTavily([make_evidence("e1", "https://blog.rust-lang.org/", 1)])
    app.state.settings.tavily_credits_per_hour = 1
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily
    app.state.verifier.buckets.settings = app.state.settings

    payload = (await call(app, "/internal/v1/verify-inline", body("r4", "cache-gamma", text))).json()
    result = payload["annotation"]["claims"][0]
    assert result["status"] == "unverifiable"
    assert result["freshness"] is None
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_concurrent_equivalent_requests_share_one_verification(app):
    text = "Python 3.14 is the latest stable release."
    claim = make_claim(text, "Python 3.14 is the latest stable release", "Python", "latest_stable_version", "3.14")
    models = FakeModels([claim], Verdict(verdict="confirmed", confidence=0.9, support_ids=["e1"]))
    tavily = FakeTavily([make_evidence("e1", "https://www.python.org/downloads/", 1)], delay=0.4)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post("/internal/v1/verify-inline", json=body("r5", "cache-delta", text), headers={"x-cg-internal-key": "i" * 40}),
            client.post("/internal/v1/verify-inline", json=body("r6", "cache-delta", text), headers={"x-cg-internal-key": "i" * 40}),
        )
    assert all(response.status_code == 200 for response in responses)
    assert {response.json()["annotation"]["claims"][0]["status"] for response in responses} <= {"fresh", "pending"}
    assert tavily.calls == 1


@pytest.mark.asyncio
async def test_revalidation_updates_the_manifest_and_revision(app):
    text = "Node.js 22 is the latest LTS release."
    claim = make_claim(text, "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    models = FakeModels([claim], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1"]))
    tavily = FakeTavily([make_evidence("e1", "https://nodejs.org/en/about/previous-releases", 1)])
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily
    await call(app, "/internal/v1/verify-inline", body("r7", "cache-epsilon", text))

    ledger_key = key("default", "manifest", "cache-epsilon")
    manifest = json.loads(await app.state.redis.get(ledger_key))
    manifest["claims"][0]["next_check_at"] = "2000-01-01T00:00:00Z"
    await app.state.redis.set(ledger_key, json.dumps(manifest))

    response = await call(
        app,
        "/internal/v1/revalidate",
        {"tenant_id": "default", "cache_id": "cache-epsilon", "policy": "strict", "deadline_ms": 3000, "reason": "due"},
    )
    result = response.json()
    assert result["status"] == "complete"
    assert result["decision"] == "serve"
    refreshed = json.loads(await app.state.redis.get(ledger_key))
    assert refreshed["rev"] == manifest["rev"] + 1
    assert refreshed["claims"][0]["status"] == "fresh"
