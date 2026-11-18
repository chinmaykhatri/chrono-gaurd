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

    Optimal unconstrained I_i* is proportional to 1 / sqrt(w_i * lambda_i).
    Clamped within [min_interval_s, max_interval_s] for each volatility class.
    """
    if not facts:
        return []

    # Budget in checks per second
    B = max(budget_checks_per_hour / 3600.0, 1e-6)
    n = len(facts)

    total_hits = sum(max(f.get("query_hits", 0), 0) for f in facts)
    use_uniform_weights = (total_hits == 0)

    prepared: list[dict[str, Any]] = []
    for f in facts:
        cat_str = str(f.get("class_key", "slow_facts"))
        try:
            cat_enum = Category(cat_str)
        except ValueError:
            cat_enum = Category.SLOW

        entry = CLASSES.get(cat_enum, CLASSES[Category.SLOW])
        _, _, c_min, c_max, _ = entry

        # Fallback interval bounds if unconstrained
        min_int = float(c_min or 3600)
        max_int = float(c_max or (30 * DAY))

        lam = float(f.get("lambda_hat") or 0.0)
        if lam <= 0.0:
            lam = default_lambda_for_class(cat_enum)

        if use_uniform_weights:
            w = 1.0 / n
        else:
            raw_hits = max(f.get("query_hits", 0), 0)
            # Add Laplace +1 to avoid zero-weight starving
            w = (raw_hits + 1.0) / (total_hits + n)

        # Base proportionality factor k_i = 1 / sqrt(w_i * lambda_i)
        k_i = 1.0 / math.sqrt(max(w * lam, 1e-12))

        prepared.append({
            "fact": f,
            "lambda": lam,
            "weight": w,
            "min_int": min_int,
            "max_int": max_int,
            "k_i": k_i,
        })

    # Initial analytic scaling factor mu_0 = (1 / B) * sum(1 / k_i)
    sum_inv_k = sum(1.0 / p["k_i"] for p in prepared)
    mu_0 = sum_inv_k / B

    def total_rate(mu: float) -> float:
        rate = 0.0
        for p in prepared:
            interval = max(p["min_int"], min(p["max_int"], mu * p["k_i"]))
            rate += 1.0 / interval
        return rate

    # Check boundaries
    min_rate_possible = sum(1.0 / p["max_int"] for p in prepared)
    max_rate_possible = sum(1.0 / p["min_int"] for p in prepared)

    if B <= min_rate_possible:
        # Budget is so tiny everyone gets max_int
        mu_star = mu_0 * 100.0
    elif B >= max_rate_possible:
        # Budget is so huge everyone gets min_int
        mu_star = mu_0 * 0.01
    else:
        # Binary search for mu in [1e-6 * mu_0, 1e6 * mu_0]
        low = mu_0 * 1e-5
        high = mu_0 * 1e5
        for _ in range(50):
            mid = (low + high) / 2.0
            r = total_rate(mid)
            if r > B:
                # Rate is too high -> need longer intervals -> increase mu
                low = mid
            else:
                high = mid
        mu_star = (low + high) / 2.0

    results = []
    for p in prepared:
        opt_interval = int(round(max(p["min_int"], min(p["max_int"], mu_star * p["k_i"]))))
        f = p["fact"]
        est_days = round(1.0 / (p["lambda"] * DAY), 1)
        results.append({
            **f,
            "lambda_hat": round(p["lambda"], 8),
            "est_change_days": est_days,
            "optimal_interval_s": opt_interval,
            "freshness_expected": round(freshness_metric(p["lambda"], opt_interval), 4),
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
