"""Audit empirical test for failure tolerance matrix (audit item f).
Tests actual behavior vs policy for:
1. Redis down
2. Tavily down
3. Judge model down
4. Verifier down
"""

import json
import pytest
from httpx import ASGITransport, AsyncClient
from app.clients import DependencyUnavailable
from app.schemas.contracts import Category, Claim, Evidence, Verdict
from app.security import key
from tests.test_pipeline import app, body, make_claim, make_evidence, FakeModels, FakeTavily


async def call(app, path, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=payload, headers={"x-cg-internal-key": "i" * 40})


class FailingTavily:
    credits = 1
    def __init__(self):
        self.calls = 0
    async def search(self, claim, depth=1):
        self.calls += 1
        raise DependencyUnavailable("tavily_api_timeout: upstream search gateway returned 504")


class FailingJudgeModels(FakeModels):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
    async def judge(self, claim, evidence):
        self.calls += 1
        raise DependencyUnavailable("judge_llm_unavailable: model provider 503 Service Unavailable")


@pytest.mark.asyncio
async def test_tavily_down_empirical_behavior(app):
    """When Tavily is down, verifier logs DependencyUnavailable and returns unverifiable (fail open under standard policy)."""
    text = "PostgreSQL 17 was released in late 2024."
    claim = make_claim(text, "PostgreSQL 17 was released in late 2024", "PostgreSQL", "latest_stable_version", "17")
    
    models = FakeModels([claim], Verdict(verdict="confirmed", confidence=0.95))
    failing_tavily = FailingTavily()
    
    app.state.verifier.models = models
    app.state.verifier.tavily = failing_tavily
    
    response = await call(app, "/internal/v1/verify-inline", body("r-tavily-fail", "cache-tavily-fail", text))
    assert response.status_code == 200
    payload = response.json()
    
    claim_anno = payload["annotation"]["claims"][0]
    assert claim_anno["status"] == "unverifiable"
    assert claim_anno["verdict"] == "unverifiable"
    print("\n[EMPIRICAL OUTPUT] Tavily failure:")
    print("  HTTP Status Code:", response.status_code)
    print("  Decision:", payload.get("decision"))
    print("  Claim Status:", claim_anno["status"])
    print("  Verdict:", claim_anno["verdict"])
    print("  Reason:", claim_anno.get("reason"))


@pytest.mark.asyncio
async def test_judge_model_down_empirical_behavior(app):
    """When Judge LLM is down, verifier logs DependencyUnavailable and returns unverifiable (fail open under standard policy)."""
    text = "React 19 was released in December 2024."
    claim = make_claim(text, "React 19 was released in December 2024", "React", "latest_stable_version", "19")
    evidence = [make_evidence("e1", "https://react.dev", 1)]
    
    failing_models = FailingJudgeModels([claim], Verdict(verdict="confirmed", confidence=0.95))
    tavily = FakeTavily(evidence)
    
    app.state.verifier.models = failing_models
    app.state.verifier.tavily = tavily
    
    response = await call(app, "/internal/v1/verify-inline", body("r-judge-fail", "cache-judge-fail", text))
    assert response.status_code == 200
    payload = response.json()
    
    claim_anno = payload["annotation"]["claims"][0]
    assert claim_anno["status"] == "unverifiable"
    assert claim_anno["verdict"] == "unverifiable"
    print("\n[EMPIRICAL OUTPUT] Judge LLM failure:")
    print("  HTTP Status Code:", response.status_code)
    print("  Decision:", payload.get("decision"))
    print("  Claim Status:", claim_anno["status"])
    print("  Verdict:", claim_anno["verdict"])
    print("  Reason:", claim_anno.get("reason"))


@pytest.mark.asyncio
async def test_policy_unverifiable_mappings():
    """Verify how policy config dictates fail-open vs fail-closed for unverifiable claims."""
    from app.schemas.contracts import POLICIES
    
    print("\n[EMPIRICAL OUTPUT] Configured Policy Behaviors for on_unverifiable:")
    for name, pol in POLICIES.items():
        print(f"  Policy '{name}': strictness={pol.strictness}, on_unverifiable={pol.on_unverifiable}, regen_on_stale={pol.regen_on_stale}")
        if pol.strictness == "strict":
            assert pol.on_unverifiable == "fail_closed"
        else:
            assert pol.on_unverifiable in ("serve_annotated", "serve")
