import json
from pathlib import Path
import pytest
from app.eval_runner import EvalService

DATASET_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "dataset" / "freshqa-100.json"


def test_freshqa_dataset_structure():
    assert DATASET_PATH.exists(), f"FreshQA dataset missing at {DATASET_PATH}"
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["id"] == "freshqa-100"
    assert data["license"] == "Apache-2.0"
    assert data["provenance"] == "external_benchmark"
    items = data["items"]
    assert len(items) == 100

    breakdown = data["breakdown"]
    assert breakdown["fast_changing"] == 50
    assert breakdown["slow_changing"] == 30
    assert breakdown["never_changing"] == 20

    # Ensure every item has required fields
    for item in items:
        assert "id" in item
        assert "prompt" in item
        assert "answer_text" in item
        assert "claim_text" in item
        assert "fact_key" in item
        assert item["label"] in ("outdated", "current")
        assert item["provenance"] == "external_benchmark"
        assert item["label_method"] == "llm_match"


def test_eval_service_freshqa_integration():
    svc = EvalService()
    datasets = svc.list_datasets()
    ds_ids = [d["id"] for d in datasets]
    assert "freshqa-100" in ds_ids

    ds = svc.get_dataset("freshqa-100")
    assert ds is not None
    assert ds["item_count"] == 100
    assert ds["provenance"] == "external_benchmark"


def test_freshqa_run_and_metrics():
    svc = EvalService()
    run = svc.create_run(
        dataset_id="freshqa-100",
        variants=["B0", "B2", "B3", "CG_full"],
        model="gpt-4o",
        run_id="test-freshqa-run",
    )
    assert run["status"] == "complete"
    assert run["dataset_id"] == "freshqa-100"

    report = run["report"]
    assert "metrics" in report
    assert "variants" in report
    assert "per_fact_type" in report

    # Check that variants include B0, B2, B3, CG_full
    v_names = [v["variant"] for v in report["variants"]]
    assert any("B0" in name for name in v_names)
    assert any("B2" in name for name in v_names)
    assert any("B3" in name for name in v_names)
    assert any("ChronoGuard Full" in name for name in v_names)

    # Check per_fact_type breakdown
    pft = report["per_fact_type"]
    assert len(pft) == 3
    types = [t["fact_type"] for t in pft]
    assert "fast_changing" in types
    assert "slow_changing" in types
    assert "never_changing" in types
