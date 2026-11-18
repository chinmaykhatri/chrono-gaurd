import math
import pytest
from app.schemas.contracts import Category
from app.scoring.freshness import DAY
from app.pipeline.scheduler import (
    estimate_lambda,
    freshness_metric,
    solve_lagrangian_budget,
    schedule_refresh_interval,
    default_lambda_for_class,
)


def test_estimator_synthetic_event_series():
    # 1. Zero changes observed over 10 checks at 7-day intervals -> lambda_hat == 0 -> falls back to class default rate
    lam_zero = estimate_lambda(n_checks=10, n_changed=0, mean_interval_s=7 * DAY, category=Category.SOFTWARE)
    expected_default = default_lambda_for_class(Category.SOFTWARE)
    assert math.isclose(lam_zero, expected_default, rel_tol=1e-5)

    # 2. 5 changes out of 10 checks -> expected half-life ~ 7-14 days
    lam_active = estimate_lambda(n_checks=10, n_changed=5, mean_interval_s=7 * DAY, category=Category.SOFTWARE)
    half_life_days = (math.log(2) / lam_active) / DAY
    # Half life should be reasonable (between 5 and 30 days)
    assert 5.0 <= half_life_days <= 30.0

    # 3. Fallback on invalid inputs (0 checks, negative interval)
    lam_fallback = estimate_lambda(n_checks=0, n_changed=0, mean_interval_s=0, category=Category.SOFTWARE)
    assert math.isclose(lam_fallback, expected_default, rel_tol=1e-5)


def test_freshness_metric():
    lam = 1.0 / (10 * DAY)
    # At interval = 0, freshness = 1.0
    assert freshness_metric(lam, 0) == 1.0

    # At interval = 10 days (1 / lambda), F = (1 - e^-1) / 1 = 0.6321
    f_1 = freshness_metric(lam, 10 * DAY)
    assert math.isclose(f_1, (1.0 - math.exp(-1.0)), rel_tol=1e-3)

    # At very long interval (100 days), freshness drops significantly
    f_long = freshness_metric(lam, 100 * DAY)
    assert f_long < 0.2


def test_zero_traffic_receives_longer_intervals_than_high_traffic():
    # Two software version facts with IDENTICAL change rate lambda
    lam = 1.0 / (14 * DAY)
    facts = [
        {
            "fact_key": "software_versions:high_traffic:v",
            "class_key": "software_versions",
            "query_hits": 500,  # High traffic
            "lambda_hat": lam,
        },
        {
            "fact_key": "software_versions:zero_traffic:v",
            "class_key": "software_versions",
            "query_hits": 0,  # Zero traffic
            "lambda_hat": lam,
        },
    ]

    budget_checks_per_hour = 0.02
    allocated = solve_lagrangian_budget(facts, budget_checks_per_hour)

    high_traffic_alloc = next(f for f in allocated if "high_traffic" in f["fact_key"])
    zero_traffic_alloc = next(f for f in allocated if "zero_traffic" in f["fact_key"])

    # High traffic fact MUST be checked much more frequently (shorter interval)
    assert high_traffic_alloc["optimal_interval_s"] < zero_traffic_alloc["optimal_interval_s"]


def test_lagrange_budget_constraint_satisfied_within_5_percent():
    # 20 facts across different classes with varying traffic
    facts = []
    classes = [
        ("software_versions", 1.0 / (21 * DAY)),
        ("pricing_plans", 1.0 / (14 * DAY)),
        ("org_people", 1.0 / (90 * DAY)),
        ("slow_facts", 1.0 / (365 * DAY)),
    ]
    for i in range(20):
        cls_key, lam = classes[i % len(classes)]
        facts.append({
            "fact_key": f"{cls_key}:entity_{i}:attr",
            "class_key": cls_key,
            "query_hits": (i * 15) % 100,
            "lambda_hat": lam,
        })

    budget_checks_per_hour = 0.2  # 0.2 checks / hour across 20 multi-day facts
    allocated = solve_lagrangian_budget(facts, budget_checks_per_hour)

    # Compute actual checks per hour resulting from optimal intervals
    actual_checks_per_hour = sum(3600.0 / f["optimal_interval_s"] for f in allocated)

    # Verify budget constraint is satisfied within 5% tolerance
    relative_diff = abs(actual_checks_per_hour - budget_checks_per_hour) / budget_checks_per_hour
    assert relative_diff <= 0.05, f"Budget diff was {relative_diff:.4f} (> 0.05). Actual: {actual_checks_per_hour}, Target: {budget_checks_per_hour}"


def test_schedule_refresh_interval_mode_dispatch():
    # 1. Standard mode uses adaptive multiplier
    interval_std, _ = schedule_refresh_interval(
        category=Category.SOFTWARE,
        verdict="confirmed",
        current_interval=172800,
        n_checks=5,
        n_changed=0,
        query_hits=10,
        mode="standard",
    )
    assert interval_std == int(172800 * 1.6)

    # 2. Optimal mode uses Lagrangian budget allocation
    interval_opt, lam = schedule_refresh_interval(
        category=Category.SOFTWARE,
        verdict="confirmed",
        current_interval=172800,
        n_checks=5,
        n_changed=0,
        query_hits=100,
        mode="optimal",
        budget_checks_per_hour=200,
    )
    assert lam > 0.0
    assert interval_opt >= 172800  # Stays within class bounds
