"""Prompt classification and per-class Tavily profiles.

The classifier mirrors the gateway's pattern-only classifier so a prompt
resolved in the console matches the class the gateway stamps. Patterns are a
routing hint, never evidence.
"""

import math
import re

from app.schemas.contracts import Category, Claim
from app.scoring.freshness import CLASSES

PATTERNS = (
    (Category.REALTIME, re.compile(r"(?i)\b(stock price|exchange rate|weather|live score|forex)\b")),
    (Category.NEWS, re.compile(r"(?i)\b(today|this week|recently|announced|breaking news)\b")),
    (Category.PRICING, re.compile(r"(?i)\b(price|pricing|cost per|quota|rate limit)\b")),
    (Category.SOFTWARE, re.compile(r"(?i)\b(version|release|api|deprecated|latest stable)\b")),
    (Category.REGULATION, re.compile(r"(?i)\b(law|tax rate|regulation|deadline|compliance)\b")),
    (Category.PEOPLE, re.compile(r"(?i)\b(ceo|founder|headcount|leadership)\b")),
)

# Document 4, section 4.5.6. These are starting profiles, not universal truth.
PROFILES = {
    Category.SLOW: {"depth": "basic", "topic": "general", "results": 5, "time_range": None},
    Category.PEOPLE: {"depth": "basic", "topic": "general", "results": 5, "time_range": None},
    Category.SOFTWARE: {"depth": "advanced", "topic": "general", "results": 5, "time_range": None},
    Category.PRICING: {"depth": "advanced", "topic": "general", "results": 5, "time_range": None},
    Category.REGULATION: {"depth": "advanced", "topic": "general", "results": 5, "time_range": None},
    Category.NEWS: {"depth": "basic", "topic": "news", "results": 6, "time_range": "week"},
    Category.REALTIME: {"depth": "basic", "topic": "finance", "results": 5, "time_range": "day"},
}


def prompt_class(text: str) -> Category:
    tail = text[-2000:] if len(text) > 2000 else text
    for category, pattern in PATTERNS:
        if pattern.search(tail):
            return category
    lowered = tail.lower()
    if "current" in lowered or "latest" in lowered:
        return Category.NEWS
    return Category.SLOW


def profile(category: Category) -> dict:
    return PROFILES.get(category, PROFILES[Category.SLOW])


def estimated_credits(category: Category) -> float:
    return 2.0 if profile(category)["depth"] == "advanced" else 1.0


def soft_ttl(category: Category):
    return CLASSES[category][1]


def priority(claim: Claim, as_of_stale: float, hits: int = 0) -> float:
    """Document 4, 4.5.5. Cost units are the configured search credits."""
    salience = CLASSES[claim.class_key][4]
    cost = estimated_credits(claim.class_key)
    return (
        as_of_stale
        * salience
        * max(0.0, min(1.0, claim.importance))
        * (1 + math.log1p(max(0, hits)))
        / max(0.1, cost)
    )
