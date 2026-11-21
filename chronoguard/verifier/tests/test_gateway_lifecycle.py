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


def make_evidence(identity, url, tier=1, snippet="Official current release information."):
    return Evidence(
        id=identity,
        url=url,
        domain=urlsplit(url).hostname,
        title="Release Information",
        snippet=snippet,
        retrieved_at=datetime.now(timezone.utc),
        tier=tier,
    )


class FakeModels:
    def __init__(self, claims=None, verdict=None):
        self.claims = claims or []
        self.verdict = verdict or Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1", "e2"])
        self.extract_calls = 0
        self.judge_calls = 0

    async def extract(self, text):
        self.extract_calls += 1
        return self.claims, {"input_tokens": 15, "output_tokens": 15}

    async def judge(self, claim, evidence):
        self.judge_calls += 1
        return self.verdict, {"input_tokens": 25, "output_tokens": 10}


class FakeTavily:
    def __init__(self, evidence=None, delay=0.0):
        self.evidence = evidence or []
        self.calls = 0
        self.delay = delay

    async def search(self, claim, depth="basic"):
        self.calls += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return self.evidence, {"credits": 2.0}


def body(request_id, cache_id, text, policy="strict", prompt_class="software_versions"):
    return {
        "tenant_id": "default",
        "request_id": request_id,
        "cache_id": cache_id,
        "origin": "provider",
        "model_id": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "What is the latest release?"}],
        "response_text": text,
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "prompt_class": prompt_class,
        "policy": policy,
        "deadline_ms": 5000,
    }


@pytest.fixture
async def app(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'gateway_test.db'}")
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
        tenant_id="default",
        allow_simulated_clock=True,
    )
    application = create_app(settings=settings, database=database, redis_client=redis_client)
    async with application.router.lifespan_context(application):
        yield application


async def call(app, path, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=payload, headers={"x-cg-internal-key": "k" * 40})


@pytest.mark.asyncio
async def test_cache_miss_extraction_and_manifest_indexing(app):
    text = "Python 3.12 is the latest stable version and Django 5.0 is supported."
    c1 = make_claim(text, "Python 3.12 is the latest stable version", "Python", "latest_stable_version", "3.12")
    c2 = make_claim(text, "Django 5.0 is supported", "Django", "supported_version", "5.0")
    evidence = [
        make_evidence("e1", "https://docs.python.org/release/3.12", 1),
        make_evidence("e2", "https://docs.djangoproject.com/release/5.0", 1),
    ]

    models = FakeModels([c1, c2], Verdict(verdict="confirmed", confidence=0.98, support_ids=["e1", "e2"]))
    tavily = FakeTavily(evidence)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    # Cache miss ingestion
    resp = await call(app, "/internal/v1/verify-inline", body("req-001", "cache-entry-alpha", text))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "complete"
    assert len(payload["annotation"]["claims"]) == 2

    # Verify Manifest stored in Redis with status "fresh"
    manifest_raw = await app.state.redis.get(key("default", "manifest", "cache-entry-alpha"))
    assert manifest_raw is not None
    manifest = json.loads(manifest_raw)
    assert manifest["status"] == "fresh"
    assert manifest["rev"] == 1
    assert len(manifest["claims"]) == 2

    # Verify reverse index cg:idx:fact:{hash} contains cache-entry-alpha
    fact_hash_1 = digest(manifest["claims"][0]["fact_key"])
    fact_hash_2 = digest(manifest["claims"][1]["fact_key"])
    idx_1 = await app.state.redis.smembers(key("default", "idx", "fact:" + fact_hash_1))
    idx_2 = await app.state.redis.smembers(key("default", "idx", "fact:" + fact_hash_2))
    assert "cache-entry-alpha" in idx_1
    assert "cache-entry-alpha" in idx_2


@pytest.mark.asyncio
async def test_fact_deduplication_zero_tavily(app):
    text1 = "Python 3.12 is the latest stable version."
    c1 = make_claim(text1, "Python 3.12 is the latest stable version", "Python", "latest_stable_version", "3.12")
    evidence = [make_evidence("e1", "https://www.python.org/downloads", 1)]

    models = FakeModels([c1], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1"]))
    tavily = FakeTavily(evidence)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    # First request verifies Python 3.12
    await call(app, "/internal/v1/verify-inline", body("req-002", "cache-entry-1", text1))
    assert tavily.calls == 1

    # Second request asks differently, but resolves to the exact same canonical fact (Python:latest_stable_version)
    text2 = "The current release is Python 3.12."
    c2 = make_claim(text2, "The current release is Python 3.12", "Python", "latest_stable_version", "3.12")
    models.claims = [c2]

    resp2 = await call(app, "/internal/v1/verify-inline", body("req-003", "cache-entry-2", text2))
    assert resp2.status_code == 200
    p2 = resp2.json()
    assert p2["annotation"]["claims"][0]["verdict"] == "confirmed"

    # Zero additional Tavily searches made! Instant Fact Ledger reuse!
    assert tavily.calls == 1

    fact_id = (await app.state.repo.list(db.facts, "default"))["items"][0]["id"]
    detail = await app.state.repo.fact_detail("default", fact_id)
    assert len(detail["entries"]) == 2
    assert detail["history"] and detail["evidence"][0]["url"] == evidence[0].url
    assert await app.state.repo.fact_detail("other-tenant", fact_id) is None
    claim_id = detail["history"][0]["claim_id"]
    session_id = "fact-operator"
    await app.state.redis.set("cg:session:" + digest(session_id),
                              json.dumps({"tenant_id": "default", "authenticated": True, "csrf_token": "csrf"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies={"cg_session": session_id}, headers={"Origin": "http://localhost:3000", "X-CSRF-Token": "csrf"}) as client:
        for route in (f"facts/{fact_id}", f"claims/{claim_id}"):
            checked = await client.post(f"/api/v1/{route}/reverify")
            assert checked.status_code == 200, checked.text


@pytest.mark.asyncio
async def test_two_key_invalidation_and_cascade_to_manifests(app):
    # Setup two entries referencing Python 3.12 and one unrelated entry referencing Go 1.22
    text1 = "Python 3.12 is the current release."
    c1 = make_claim(text1, "Python 3.12 is the current release", "Python", "latest_stable_version", "3.12")

    text2 = "Python 3.12 is the stable version."
    c2 = make_claim(text2, "Python 3.12 is the stable version", "Python", "latest_stable_version", "3.12")

    text3 = "Go 1.22 is the latest release."
    c3 = make_claim(text3, "Go 1.22 is the latest release", "Go", "latest_stable_version", "1.22")

    evidence_py = [
        make_evidence("e1", "https://python.org", 1),
        make_evidence("e2", "https://docs.python.org", 2),
    ]
    evidence_go = [
        make_evidence("e3", "https://golang.org", 1),
        make_evidence("e4", "https://go.dev", 2),
    ]

    models = FakeModels([c1], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1", "e2"]))
    tavily = FakeTavily(evidence_py)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    # Ingest entry 1 and entry 2 (both reference python:latest_stable_version)
    await call(app, "/internal/v1/verify-inline", body("r1", "cache-py-1", text1))
    models.claims = [c2]
    await call(app, "/internal/v1/verify-inline", body("r2", "cache-py-2", text2))

    # Ingest entry 3 (references go:latest_stable_version)
    models.claims = [c3]
    models.verdict = Verdict(verdict="confirmed", confidence=0.95, support_ids=["e3", "e4"])
    tavily.evidence = evidence_go
    await call(app, "/internal/v1/verify-inline", body("r3", "cache-go-1", text3))

    # Confirm all three are fresh
    m_py1 = json.loads(await app.state.redis.get(key("default", "manifest", "cache-py-1")))
    m_py2 = json.loads(await app.state.redis.get(key("default", "manifest", "cache-py-2")))
    m_go = json.loads(await app.state.redis.get(key("default", "manifest", "cache-go-1")))
    assert m_py1["status"] == "fresh"
    assert m_py2["status"] == "fresh"
    assert m_go["status"] == "fresh"

    # Now a new verification reveals Python 3.12 is outdated! Python 3.13 was released.
    # Meets the Two-Key rule (two tier 1/2 independent sources).
    evidence_outdated = [
        make_evidence("e_py313_a", "https://docs.python.org/release/3.13", 1, "Python 3.13 is now current."),
        make_evidence("e_py313_b", "https://github.com/python/cpython/releases/tag/v3.13.0", 2, "Python 3.13.0 final"),
    ]
    models.claims = [c1]
    models.verdict = Verdict(
        verdict="outdated",
        confidence=0.98,
        corrected_value="3.13",
        contradict_ids=["e_py313_a", "e_py313_b"],
        rationale="Python 3.13 was officially released.",
    )
    tavily.evidence = evidence_outdated

    # Force revalidation or re-verify of this claim
    reval_resp = await call(
        app,
        "/internal/v1/revalidate",
        {"tenant_id": "default", "cache_id": "cache-py-1", "policy": "strict", "deadline_ms": 5000, "reason": "due", "force": True},
    )
    assert reval_resp.status_code == 200
    res = reval_resp.json()
    assert res["decision"] in ("evict_regen", "evict_lazy")

    # CRITICAL CASCADE ASSERTION:
    # 1. cache-py-1 is marked STALE
    m_py1_updated = json.loads(await app.state.redis.get(key("default", "manifest", "cache-py-1")))
    assert m_py1_updated["status"] == "stale"
    assert m_py1_updated["claims"][0]["status"] == "stale"
    assert m_py1_updated["claims"][0]["corrected_value"] == "3.13"

    # 2. cache-py-2 MUST ALSO BE CASCADE-INVALIDATED to STALE via cg:idx:fact:{hash}
    m_py2_updated = json.loads(await app.state.redis.get(key("default", "manifest", "cache-py-2")))
    assert m_py2_updated["status"] == "stale"
    assert m_py2_updated["claims"][0]["status"] == "stale"
    assert m_py2_updated["claims"][0]["corrected_value"] == "3.13"

    # 3. cache-go-1 MUST REMAIN COMPLETELY UNTOUCHED ("fresh")
    m_go_updated = json.loads(await app.state.redis.get(key("default", "manifest", "cache-go-1")))
    assert m_go_updated["status"] == "fresh"


@pytest.mark.asyncio
async def test_decision_engine_and_grounded_regeneration_bundle(app):
    text = "Ubuntu 22.04 is the newest LTS."
    c1 = make_claim(text, "Ubuntu 22.04 is the newest LTS", "Ubuntu", "latest_lts_version", "22.04")
    evidence = [make_evidence("e1", "https://ubuntu.com/download", 1)]

    models = FakeModels([c1], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1"]))
    tavily = FakeTavily(evidence)
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    # Ingest original answer
    await call(app, "/internal/v1/verify-inline", body("r-ground-1", "cache-ubuntu", text))

    # Mark as stale with corrected value Ubuntu 24.04
    models.verdict = Verdict(
        verdict="outdated",
        confidence=0.99,
        corrected_value="24.04",
        contradict_ids=["e2", "e3"],
        rationale="Ubuntu 24.04 LTS Noble Numbat is now current.",
    )
    tavily.evidence = [
        make_evidence("e2", "https://ubuntu.com/download/desktop", 1, "Ubuntu 24.04 LTS is available now."),
        make_evidence("e3", "https://releases.ubuntu.com/24.04/", 2, "Ubuntu 24.04 LTS release"),
    ]

    # Revalidate with force to trigger eviction & grounded regeneration bundle
    reval = await call(
        app,
        "/internal/v1/revalidate",
        {"tenant_id": "default", "cache_id": "cache-ubuntu", "policy": "strict", "deadline_ms": 5000, "reason": "due", "force": True},
    )
    assert reval.status_code == 200
    reval_data = reval.json()
    assert reval_data["decision"] == "evict_regen"

    # Verify Grounding Bundle is generated with replacement info
    replacement = reval_data.get("replacement")
    assert replacement is not None
    assert "ground_id" in replacement

    ground_id = replacement["ground_id"]
    ground_raw = await app.state.redis.get(key("default", "ground", ground_id))
    assert ground_raw is not None
    ground_bundle = json.loads(ground_raw)
    assert ground_bundle["ground_id"] == ground_id
    assert ground_bundle["facts"][0]["new_value"] == "24.04"
    assert len(ground_bundle["evidence"]) > 0


@pytest.mark.asyncio
async def test_singleflight_50_concurrent_requests(app):
    text = "Redis 7.2 is the stable version."
    c1 = make_claim(text, "Redis 7.2 is the stable version", "Redis", "latest_stable_version", "7.2")
    evidence = [make_evidence("e1", "https://redis.io/download", 1)]

    models = FakeModels([c1], Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1"]))
    tavily = FakeTavily(evidence, delay=0.25)  # slight delay to ensure concurrency overlap
    app.state.verifier.models = models
    app.state.verifier.tavily = tavily

    # Fire 50 concurrent requests for the exact same unverified fact
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tasks = [
            client.post(
                "/internal/v1/verify-inline",
                json=body(f"r-conc-{i}", f"cache-conc-{i}", text),
                headers={"x-cg-internal-key": "k" * 40},
            )
            for i in range(50)
        ]
        responses = await asyncio.gather(*tasks)

    assert all(r.status_code == 200 for r in responses)
    # Tavily must only be called ONCE despite 50 concurrent clients!
    assert tavily.calls == 1
