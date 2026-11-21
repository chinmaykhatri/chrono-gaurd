"""Budget-Optimal Refresh Scheduler based on Cho & Garcia-Molina (2003).

Models fact state changes as a Poisson process with rate lambda.
Solves for the optimal verification interval allocation under a global
checks-per-hour budget constraint using Lagrangian multipliers, weighting
staleness risk by query arrival traffic.
"""

import math
from typing import Any
from app.schemas.contracts import Category
from app.scoring.freshness import CLASSES, DAY

LN_2 = math.log(2.0)


def default_lambda_for_class(category: Category | str) -> float:
    """Default Poisson rate lambda = ln(2) / half_life."""
    cat_enum = category if isinstance(category, Category) else Category(str(category))
    entry = CLASSES.get(cat_enum)
    if not entry or entry[0] is None or entry[0] <= 0:
        return 1.0 / (365.0 * DAY)
    half_life = float(entry[0])
    return LN_2 / half_life


def estimate_lambda(
    n_checks: int,
    n_changed: int,
    mean_interval_s: float,
    category: Category | str,
) -> float:
    """Cho & Garcia-Molina (2003) Poisson rate estimator with Jeffreys prior.

    lambda_hat = - (1 / I_bar) * ln((n - X + 0.5) / (n + 0.5))
    """
    default_rate = default_lambda_for_class(category)
    if n_checks <= 0 or mean_interval_s <= 0:
        return default_rate

    n = float(n_checks)
    X = float(min(n_changed, n_checks))
    ratio = (n - X + 0.5) / (n + 0.5)

    if ratio <= 0.0 or ratio >= 1.0:
        # If ratio >= 1 (e.g. invalid counts), or ratio <= 0, fall back gracefully
        if ratio >= 1.0:
            return default_rate
        return default_rate * 2.0

    rate = -(1.0 / mean_interval_s) * math.log(ratio)
    # Clamp to physically reasonable rates (between once every 5 years and once every minute)
    min_rate = 1.0 / (5.0 * 365.0 * DAY)
    max_rate = 1.0 / 60.0
    return max(min_rate, min(max_rate, rate))


def freshness_metric(lambda_rate: float, interval_s: float) -> float:
    """Cho & Garcia-Molina freshness metric F(lambda, I) = (1 - exp(-lambda * I)) / (lambda * I)."""
    if lambda_rate <= 0.0 or interval_s <= 0.0:
        return 1.0
    x = lambda_rate * interval_s
    if x < 1e-4:
        return 1.0 - (x / 2.0) + (x * x / 6.0)
    return (1.0 - math.exp(-x)) / x


def solve_lagrangian_budget(
    facts: list[dict[str, Any]],
    budget_checks_per_hour: float,
) -> list[dict[str, Any]]:
    """Solve for optimal verification intervals under a checks/hour budget constraint.

    min sum_i w_i * (1 - F(lambda_i, I_i))
    subject to sum_i (1 / I_i) <= B, where w_i = hits_i / sum hits.

    Solve the concave objective over refresh rates with a common price
    for each budget unit. A fact may consume multiple units per check.
    """
    if not facts:
        return []

    # Budget in checks per second
    B = max(budget_checks_per_hour / 3600.0, 1e-6)
    n = len(facts)

    total_hits = sum(max(f.get("query_hits", 0), 0) for f in facts)
    prepared = []
    for fact in facts:
        try:
            category = Category(fact.get("class_key", Category.SLOW))
        except ValueError:
            category = Category.SLOW
        _, _, minimum, maximum, _ = CLASSES[category]
        lam = float(fact.get("lambda_hat") or default_lambda_for_class(category))
        weight = (max(fact.get("query_hits", 0), 0) + 1) / (total_hits + n)
        cost = max(float(fact.get("credits_per_check", 1)), 1e-9)
        prepared.append((fact, lam, weight, cost, 1 / (maximum or 30 * DAY), 1 / (minimum or 3600)))

    def marginal(lam, weight, rate):
        x = lam / rate
        if x < 1e-4:
            return weight / lam * (x * x / 2 - x * x * x / 3)
        return weight / lam * (-math.expm1(-x) - x * math.exp(-x))

    def rate_at(fact, price):
        _, lam, weight, cost, low, high = fact
        target = price * cost
        if marginal(lam, weight, low) <= target:
            return low
        if marginal(lam, weight, high) >= target:
            return high
        for _ in range(28):
            mid = (low + high) / 2
            if marginal(lam, weight, mid) > target:
                low = mid
            else:
                high = mid
        return low

    minimum_rate = sum(cost * low for _, _, _, cost, low, _ in prepared)
    maximum_rate = sum(cost * high for _, _, _, cost, _, high in prepared)
    affordable = B >= minimum_rate
    if not affordable:
        rates = [item[4] for item in prepared]
    elif B >= maximum_rate:
        rates = [item[5] for item in prepared]
    else:
        lower = 0.0
        upper = max(marginal(lam, weight, low) / cost for _, lam, weight, cost, low, _ in prepared)
        for _ in range(40):
            price = (lower + upper) / 2
            spend = sum(fact[3] * rate_at(fact, price) for fact in prepared)
            if spend > B:
                lower = price
            else:
                upper = price
        rates = [rate_at(item, upper) for item in prepared]

    results = []
    for item, rate in zip(prepared, rates, strict=True):
        fact, lam, _, _, _, _ = item
        interval = math.ceil(1 / rate - 1e-9)
        results.append({
            **fact,
            "lambda_hat": lam,
            "est_change_days": round(1.0 / (lam * DAY), 1),
            "optimal_interval_s": interval,
            "freshness_expected": round(freshness_metric(lam, interval), 4),
            "budget_feasible": affordable,
        })
    return results


def schedule_refresh_interval(
    category: Category | str,
    verdict: str,
    current_interval: int,
    n_checks: int,
    n_changed: int,
    query_hits: int,
    mode: str = "standard",
    budget_checks_per_hour: float = 100.0,
) -> tuple[int, float]:
    """Compute refresh interval and lambda_hat.

    If mode == "optimal", computes Lagrangian-optimal interval.
    Otherwise falls back to adaptive interval.
    """
    cat_str = category.value if hasattr(category, "value") else str(category)
    try:
        cat_enum = Category(cat_str)
    except ValueError:
        cat_enum = Category.SLOW

    entry = CLASSES.get(cat_enum, CLASSES[Category.SLOW])
    _, initial, c_min, c_max, _ = entry
    cur = current_interval or initial or 3600

    # Compute updated lambda_hat
    lam = estimate_lambda(n_checks, n_changed, float(cur), cat_enum)

    if mode != "optimal":
        # Adaptive interval standard fallback
        if verdict == "confirmed":
            interval = int(min(c_max, max(cur, 1) * 1.6))
        elif verdict in ("outdated", "contradicted"):
            interval = int(max(c_min, cur * 0.5))
        else:
            interval = int(max(c_min, cur / 4))
        return interval, lam

    # Optimal mode for single fact update
    dummy_fact = {
        "class_key": cat_str,
        "query_hits": query_hits,
        "lambda_hat": lam,
    }
    res = solve_lagrangian_budget([dummy_fact], budget_checks_per_hour)
    optimal_int = res[0]["optimal_interval_s"] if res else cur
    return optimal_int, lam
