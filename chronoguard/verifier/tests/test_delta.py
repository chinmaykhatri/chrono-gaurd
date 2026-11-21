import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4
import fakeredis.aioredis
import httpx
import pytest
from pydantic import SecretStr

from app import db
from app.config import Settings
from app.pipeline.normalize import fact_key
from app.pipeline.verify import Verifier, Outcome
from app.repository import Repository
from app.schemas.contracts import POLICIES, Category, Claim, Evidence, Verdict
from app.security import digest, key


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


class FakeModels:
    def __init__(self, verdict):
        self.verdict = verdict
        self.judge_calls = 0

    async def judge(self, claim, evidence):
        self.judge_calls += 1
        verdict = self.verdict
        if verdict.verdict == "outdated" and evidence:
            verdict = verdict.model_copy(update={"contradict_ids": [evidence[0].id]})
        return verdict, {"input_tokens": 50, "output_tokens": 15}


class FakeTavily:
    def __init__(self, evidence):
        self.evidence = evidence
        self.search_calls = 0

    async def search(self, claim, depth="basic"):
        self.search_calls += 1
        return self.evidence, {"credits": 2.0}


class FakeClock:
    def __init__(self, now):
        self._now = now

    async def now(self):
        return self._now


class FakeBuckets:
    async def take(self, tenant, bucket, amount):
        return True

    async def refund(self, tenant, bucket, amount):
        return True


@pytest.fixture
async def setup_verifier(tmp_path, monkeypatch):
    async def public_test_host(self, host):
        return host == "nodejs.org"

    monkeypatch.setattr(Verifier, "_resolve_public", public_test_host)
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'verifier_delta.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(db.metadata.create_all)
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    repo = Repository(database)
    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite://"),
        redis_url=SecretStr("redis://localhost:6379/0"),
        internal_key=SecretStr("k" * 40),
        session_secret=SecretStr("s" * 40),
        admin_password_hash=SecretStr("$argon2id$v=19$m=65536,t=3,p=4$fake$hash"),
        console_origin="http://localhost:3000",
        tenant_id="default",
        delta_enabled=True,
        delta_source_urls=["https://nodejs.org/en/about/releases"],
        source_authorities={"nodejs.org": 1},
    )
    now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(now)
    buckets = FakeBuckets()

    return database, redis_client, repo, settings, now, clock, buckets


@pytest.mark.asyncio
async def test_delta_revalidation_304(setup_verifier):
    database, redis_client, repo, settings, now, clock, buckets = setup_verifier
    tenant = "default"

    claim = make_claim("Node.js 22 is the latest LTS release.", "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    fkey, _ = fact_key(claim)
    fhash = digest(fkey)
    target_url = "https://nodejs.org/en/about/releases"
    orig_text = "Node.js 22 is the active LTS release."
    orig_hash = digest(orig_text)

    await redis_client.hset(
        key(tenant, "fact", fhash),
        mapping={
            "fact_key": fkey,
            "class_key": "software_versions",
            "current_value": "22",
            "last_verdict": "confirmed",
            "fresh_until": "2026-11-19T10:00:00Z",  # Expired 2 hours ago
            "freshness": "95",
            "support_confidence": "0.98",
            "verified_at": "2026-11-18T10:00:00Z",
            "interval_s": "3600",
            "source_urls": json.dumps([target_url]),
            "source_text_hash": orig_hash,
            "source_etag": '"fixture-v1"',
            "evidence": "[]",
        },
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"fixture-v1"'
        return httpx.Response(304)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    models = FakeModels(Verdict(verdict="confirmed"))
    tavily = FakeTavily([])

    verifier = Verifier(
        settings=settings,
        repository=repo,
        redis=redis_client,
        clock=clock,
        models=models,
        tavily=tavily,
        buckets=buckets,
        http_client=mock_client,
    )

    policy = POLICIES["strict"]

    outcome = await verifier.verify_claim(tenant, claim, policy, now, "gpt-4o", deadline=time_monotonic() + 10.0)

    assert outcome.status == "fresh"
    assert outcome.verdict == "confirmed"
    assert outcome.delta_confirmed is True
    assert outcome.credits == 0.0
    assert outcome.tokens == 0
    assert tavily.search_calls == 0
    assert models.judge_calls == 0


@pytest.mark.asyncio
async def test_delta_revalidation_hash_match(setup_verifier):
    database, redis_client, repo, settings, now, clock, buckets = setup_verifier
    tenant = "default"

    claim = make_claim("Node.js 22 is the latest LTS release.", "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    fkey, _ = fact_key(claim)
    fhash = digest(fkey)
    target_url = "https://nodejs.org/en/about/releases"
    orig_text = "Node.js 22 is the active LTS release."
    orig_hash = digest(orig_text)

    await redis_client.hset(
        key(tenant, "fact", fhash),
        mapping={
            "fact_key": fkey,
            "class_key": "software_versions",
            "current_value": "22",
            "last_verdict": "confirmed",
            "fresh_until": "2026-11-19T10:00:00Z",
            "freshness": "95",
            "support_confidence": "0.98",
            "verified_at": "2026-11-18T10:00:00Z",
            "interval_s": "3600",
            "source_urls": json.dumps([target_url]),
            "source_text_hash": orig_hash,
            "source_etag": '"fixture-v1"',
            "evidence": "[]",
        },
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=orig_text)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    models = FakeModels(Verdict(verdict="confirmed"))
    tavily = FakeTavily([])

    verifier = Verifier(
        settings=settings,
        repository=repo,
        redis=redis_client,
        clock=clock,
        models=models,
        tavily=tavily,
        buckets=buckets,
        http_client=mock_client,
    )

    policy = POLICIES["strict"]

    outcome = await verifier.verify_claim(tenant, claim, policy, now, "gpt-4o", deadline=time_monotonic() + 10.0)

    assert outcome.status == "fresh"
    assert outcome.verdict == "confirmed"
    assert outcome.delta_confirmed is True
    assert outcome.credits == 0.0
    assert outcome.tokens == 0
    assert tavily.search_calls == 0
    assert models.judge_calls == 0


@pytest.mark.asyncio
async def test_delta_revalidation_text_changed(setup_verifier):
    database, redis_client, repo, settings, now, clock, buckets = setup_verifier
    tenant = "default"

    claim = make_claim("Node.js 22 is the latest LTS release.", "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    fkey, _ = fact_key(claim)
    fhash = digest(fkey)
    target_url = "https://nodejs.org/en/about/releases"
    orig_text = "Node.js 22 is the active LTS release."
    orig_hash = digest(orig_text)

    await redis_client.hset(
        key(tenant, "fact", fhash),
        mapping={
            "fact_key": fkey,
            "class_key": "software_versions",
            "current_value": "22",
            "last_verdict": "confirmed",
            "fresh_until": "2026-11-19T10:00:00Z",
            "freshness": "95",
            "support_confidence": "0.98",
            "verified_at": "2026-11-18T10:00:00Z",
            "interval_s": "3600",
            "source_urls": json.dumps([target_url]),
            "source_text_hash": orig_hash,
            "source_etag": '"fixture-v1"',
            "evidence": "[]",
        },
    )

    new_text = "Node.js 24 is now the latest stable LTS release."

    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=new_text)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    models = FakeModels(Verdict(verdict="outdated", corrected_value="24", confidence=0.95, rationale="Node.js 24 is now LTS"))
    tavily = FakeTavily([])

    verifier = Verifier(
        settings=settings,
        repository=repo,
        redis=redis_client,
        clock=clock,
        models=models,
        tavily=tavily,
        buckets=buckets,
        http_client=mock_client,
    )

    policy = POLICIES["strict"]

    outcome = await verifier.verify_claim(tenant, claim, policy, now, "gpt-4o", deadline=time_monotonic() + 10.0)

    assert outcome.status == "stale"
    assert outcome.verdict == "outdated"
    assert outcome.corrected_value == "24"
    assert outcome.credits == 0.0  # Search credits skipped!
    assert outcome.tokens > 0  # Judge model was called on new text
    assert tavily.search_calls == 0
    assert models.judge_calls == 1


@pytest.mark.asyncio
async def test_delta_revalidation_404_fallback(setup_verifier):
    database, redis_client, repo, settings, now, clock, buckets = setup_verifier
    tenant = "default"

    claim = make_claim("Node.js 22 is the latest LTS release.", "Node.js 22 is the latest LTS release", "Node.js", "latest_stable_version", "22")
    fkey, _ = fact_key(claim)
    fhash = digest(fkey)
    target_url = "https://nodejs.org/en/about/releases"
    orig_text = "Node.js 22 is the active LTS release."
    orig_hash = digest(orig_text)

    await redis_client.hset(
        key(tenant, "fact", fhash),
        mapping={
            "fact_key": fkey,
            "class_key": "software_versions",
            "current_value": "22",
            "last_verdict": "confirmed",
            "fresh_until": "2026-11-19T10:00:00Z",
            "freshness": "95",
            "support_confidence": "0.98",
            "verified_at": "2026-11-18T10:00:00Z",
            "interval_s": "3600",
            "source_urls": json.dumps([target_url]),
            "source_text_hash": orig_hash,
            "source_etag": '"fixture-v1"',
            "evidence": "[]",
        },
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    models = FakeModels(Verdict(verdict="confirmed"))
    fallback_evidence = [
        Evidence(
            id=str(uuid4()),
            url="https://nodejs.org/en",
            domain="nodejs.org",
            title="Node.js",
            snippet="Node.js 22 LTS",
            retrieved_at=now,
            tier=1,
        )
    ]
    tavily = FakeTavily(fallback_evidence)

    verifier = Verifier(
        settings=settings,
        repository=repo,
        redis=redis_client,
        clock=clock,
        models=models,
        tavily=tavily,
        buckets=buckets,
        http_client=mock_client,
    )

    policy = POLICIES["strict"]

    outcome = await verifier.verify_claim(tenant, claim, policy, now, "gpt-4o", deadline=time_monotonic() + 10.0)

    assert tavily.search_calls == 1  # Successfully fell back to Tavily!
    assert outcome.credits == 2.0


def time_monotonic():
    import time
    return time.monotonic()
