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
    assert data["provenance"] == "curated_fixture"
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
        assert item["provenance"] == "curated_fixture"
        assert item["label_method"] == "fixture_labels"


def test_eval_service_freshqa_integration():
    svc = EvalService()
    datasets = svc.list_datasets()
    ds_ids = [d["id"] for d in datasets]
    assert "freshqa-100" in ds_ids

    ds = svc.get_dataset("freshqa-100")
    assert ds is not None
    assert ds["item_count"] == 100
    assert ds["provenance"] == "curated_fixture"


def test_unmeasured_fixture_does_not_publish_metrics():
    svc = EvalService()

    with pytest.raises(ValueError, match="does not have a runnable replay"):
        svc.create_run("freshqa-100")
    assert svc.list_runs() == []
