import math
import re
from datetime import datetime

from app.schemas.contracts import Category, Evidence, Verdict

# Experimental defaults, not guarantees. Times in seconds.
DAY = 86400
CLASSES = {
    Category.STATIC: (None, None, None, None, 0),
    Category.SLOW: (365*DAY, 90*DAY, 30*DAY, 180*DAY, .4),
    Category.PEOPLE: (90*DAY, 21*DAY, 7*DAY, 60*DAY, .8),
    Category.SOFTWARE: (21*DAY, 7*DAY, 2*DAY, 30*DAY, 1),
    Category.PRICING: (14*DAY, 3*DAY, DAY//2, 14*DAY, 1),
    Category.REGULATION: (60*DAY, 14*DAY, 3*DAY, 45*DAY, 1),
    Category.NEWS: (4*DAY, DAY, DAY//4, 3*DAY, .7),
    Category.REALTIME: (900, 0, 0, 0, 1),
}
TIER = {1: 1.0, 2: .7, 3: .4, 4: .2}


def prior_stale(category: Category, as_of: datetime | None, now: datetime):
    half_life = CLASSES[category][0]
    if half_life is None:
        return 0.0
    if as_of is None:
        return None  # Unknown model cutoffs are not manufactured as factual dates.
    age = max(0, (now-as_of).total_seconds())
    return min(.98, max(.02, 1 - 2**(-age/half_life)))


def invalidation_allowed(verdict: Verdict, evidence: list[Evidence]):
    if verdict.verdict not in ("outdated", "contradicted"):
        return False, "not_contradicted"
    contradict = [e for e in evidence if e.id in verdict.contradict_ids]
    if any(e.tier == 1 for e in contradict):
        return True, "official_contradiction"
    if len({e.domain for e in contradict if e.tier <= 2}) >= 2:
        return True, "independent_authoritative_contradictions"
    if (verdict.confidence or 0) >= .9 and verdict.corrected_value and any(
        e.tier <= 2 and re.search(r"(?<![\w.])" + re.escape(verdict.corrected_value) + r"(?![\w.]\w|\w)", e.snippet)
        for e in contradict
    ):
        return True, "high_confidence_verbatim_correction"
    return False, "evict_rule_unmet"


def score(verdict: Verdict, evidence: list[Evidence], category: Category, now: datetime, prior: float | None, coverage: float = 1):
    if verdict.verdict == "unverifiable" or verdict.confidence is None:
        return {"freshness": None, "support_confidence": None, "features": {}, "calibrated": False}
    support = [e for e in evidence if e.id in verdict.support_ids]
    contra = [e for e in evidence if e.id in verdict.contradict_ids]
    authority = max((TIER[e.tier] for e in support), default=0)
    agreement = min(1, len({e.domain for e in support}) / 2)
    dated = [e.published_at for e in support if e.published_at]
    half_life = CLASSES[category][0] or 365*DAY
    recency = 2**(-max(0, (now-max(dated)).total_seconds())/half_life) if dated else (.5 if support else 0)
    features = {"bias": -1, "verdict": {"confirmed":2.5,"outdated":-2,"contradicted":-2.5}[verdict.verdict],
                "support": 1.5*authority, "recency": .8*recency, "authority": authority,
                "agreement": .8*agreement, "coverage": .4*min(1,max(0,coverage)),
                "contradiction": -2*max((TIER[e.tier] for e in contra), default=0),
                "prior": .4*math.log((1-prior)/prior) if prior is not None and 0 < prior < 1 else 0}
    z = sum(features.values())
    deciding = support if verdict.verdict == "confirmed" else contra
    deciding_authority = max((TIER[e.tier] for e in deciding), default=0)
    deciding_agreement = min(1, len({e.domain for e in deciding})/2)
    confidence = verdict.confidence*(.5+.5*deciding_authority)*(.7+.3*deciding_agreement)
    return {"freshness": round(100/(1+math.exp(-z)), 2), "support_confidence": round(confidence, 4), "features": features, "logit": z, "calibrated": False}
