from datetime import datetime, timezone, timedelta
import pytest
from app.schemas.contracts import Category, Evidence, Verdict
from app.scoring.freshness import prior_stale, invalidation_allowed, score, CLASSES

def make_ev(e_id: str, tier: int = 1, domain: str = "example.com", snippet: str = "Test"):
    return Evidence(
        id=e_id,
        url=f"https://{domain}/page",
        domain=domain,
        title="Doc",
        snippet=snippet,
        retrieved_at=datetime.now(timezone.utc),
        tier=tier
    )

def test_prior_stale_static():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=365)
    # Static facts never decay
    assert prior_stale(Category.STATIC, cutoff, now) == 0.0

def test_prior_stale_unknown_cutoff():
    now = datetime.now(timezone.utc)
    # When cutoff is unknown, don't manufacture dates
    assert prior_stale(Category.SOFTWARE, None, now) is None

def test_prior_stale_software_decay():
    now = datetime.now(timezone.utc)
    # Software half-life is 21 days
    half_life = CLASSES[Category.SOFTWARE][0]
    cutoff_one_hl = now - timedelta(seconds=half_life)
    # At 1 half life, 1 - 2^(-1) = 0.5
    ps = prior_stale(Category.SOFTWARE, cutoff_one_hl, now)
    assert 0.49 <= ps <= 0.51

def test_invalidation_allowed_not_contradicted():
    v = Verdict(verdict="confirmed", confidence=0.95)
    allowed, reason = invalidation_allowed(v, [])
    assert not allowed
    assert reason == "not_contradicted"

def test_invalidation_allowed_official_tier1():
    e1 = make_ev("e1", tier=1, domain="docs.python.org")
    v = Verdict(verdict="outdated", confidence=0.9, contradict_ids=["e1"], corrected_value="Python 3.12")
    allowed, reason = invalidation_allowed(v, [e1])
    assert allowed
    assert reason == "official_contradiction"

def test_invalidation_allowed_two_tier2_domains():
    e1 = make_ev("e1", tier=2, domain="github.com")
    e2 = make_ev("e2", tier=2, domain="pypi.org")
    v = Verdict(verdict="outdated", confidence=0.85, contradict_ids=["e1", "e2"])
    allowed, reason = invalidation_allowed(v, [e1, e2])
    assert allowed
    assert reason == "independent_authoritative_contradictions"

def test_invalidation_allowed_high_confidence_verbatim():
    e1 = make_ev("e1", tier=2, domain="techblog.com", snippet="The price increased to $49 per user")
    v = Verdict(verdict="contradicted", confidence=0.95, contradict_ids=["e1"], corrected_value="$49")
    allowed, reason = invalidation_allowed(v, [e1])
    assert allowed
    assert reason == "high_confidence_verbatim_correction"

def test_invalidation_unmet_rule():
    # Only 1 tier 3 source
    e1 = make_ev("e1", tier=3, domain="forum.com", snippet="I think it changed")
    v = Verdict(verdict="contradicted", confidence=0.6, contradict_ids=["e1"])
    allowed, reason = invalidation_allowed(v, [e1])
    assert not allowed
    assert reason == "evict_rule_unmet"

def test_score_unverifiable():
    v = Verdict(verdict="unverifiable")
    res = score(v, [], Category.SOFTWARE, datetime.now(timezone.utc), prior=0.5)
    assert res["freshness"] is None
    assert res["support_confidence"] is None

def test_score_confirmed_high_freshness():
    now = datetime.now(timezone.utc)
    e1 = make_ev("e1", tier=1, domain="python.org")
    e1.published_at = now - timedelta(days=1)
    v = Verdict(verdict="confirmed", confidence=0.95, support_ids=["e1"])
    res = score(v, [e1], Category.SOFTWARE, now, prior=0.1)
    assert res["freshness"] is not None
    assert res["freshness"] > 70.0
    assert res["support_confidence"] > 0.7

