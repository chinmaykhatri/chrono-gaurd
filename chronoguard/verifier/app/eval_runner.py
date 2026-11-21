import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.release_replay import request_trace, run_replay

DATASET_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "dataset" / "stalebench-mini.json"

class EvalService:
    def __init__(self):
        self.datasets: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self._load_default_dataset()

    def _load_default_dataset(self):
        items = []
        if DATASET_PATH.exists():
            try:
                with open(DATASET_PATH, "r", encoding="utf-8") as f:
                    items = json.load(f)
            except Exception:
                items = []

        ds_id = "stalebench-mini"
        self.datasets[ds_id] = {
            "id": ds_id,
            "name": "StaleBench Mini",
            "version": "1.0.0",
            "description": "120 labeled items across 6 volatility classes plus static controls.",
            "label_date": "2026-04-15",
            "item_count": len(items),
            "items": items,
            "created_at": datetime.now(UTC).isoformat(),
        }

        freshqa_path = Path(__file__).resolve().parent.parent.parent / "eval" / "dataset" / "freshqa-100.json"
        if freshqa_path.exists():
            try:
                with open(freshqa_path, "r", encoding="utf-8") as f:
                    fqa_data = json.load(f)
                    fqa_items = fqa_data.get("items", []) if isinstance(fqa_data, dict) else fqa_data
                    self.datasets["freshqa-100"] = {
                        "id": "freshqa-100",
                        "name": "FreshQA-derived fixture",
                        "version": "1.0.0",
                        "description": "Curated FreshQA-derived prompts for future measured verification.",
                        "label_date": fqa_data.get("label_date", "2026-05-01") if isinstance(fqa_data, dict) else "2026-05-01",
                        "provenance": "curated_fixture",
                        "item_count": len(fqa_items),
                        "items": fqa_items,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
            except Exception:
                pass

        path = DATASET_PATH.with_name("release-replay.json")
        if path.is_file():
            trace = json.loads(path.read_text(encoding="utf-8"))
            items = request_trace(trace)
            self.datasets["release-replay"] = {
                **trace, "items": items, "item_count": len(items), "provenance": "controlled_replay",
            }

    def list_datasets(self) -> list[dict[str, Any]]:
        return [
            {
                "id": d["id"],
                "name": d["name"],
                "version": d["version"],
                "description": d.get("description", ""),
                "item_count": d["item_count"],
                "label_date": d["label_date"],
                "created_at": d.get("created_at"),
                "provenance": d.get("provenance"),
                "runnable": d["id"] == "release-replay",
            }
            for d in self.datasets.values()
        ]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        return self.datasets.get(dataset_id)

    def import_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload, list):
            payload = {"items": payload}
        items = payload.get("items", [])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("Dataset items must be objects.")
        ds_id = str(uuid4())
        record = {
            "id": ds_id,
            "name": payload.get("name", "Custom Dataset"),
            "version": payload.get("version", "1.0.0"),
            "description": payload.get("description", ""),
            "label_date": payload.get("label_date", datetime.now(UTC).date().isoformat()),
            "item_count": len(items),
            "items": items,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.datasets[ds_id] = record
        return record

    def list_runs(self) -> list[dict[str, Any]]:
        return [{key: value for key, value in run.items() if key != "report"} for run in self.runs.values()]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def create_run(self, dataset_id: str):
        dataset = self.get_dataset(dataset_id)
        if dataset_id != "release-replay" or dataset is None:
            raise ValueError("This dataset does not have a runnable replay.")
        rid = f"run-{uuid4().hex[:8]}"
        trace = {key: value for key, value in dataset.items() if key not in ("items", "item_count", "provenance")}
        report = run_replay(trace)
        run = {
            "id": rid, "name": dataset["name"], "dataset_id": dataset_id,
            "status": "complete", "created_at": datetime.now(UTC).isoformat(),
            "done": dataset["item_count"], "total": dataset["item_count"],
        }
        self.runs[rid] = {**run, "report": report}
        return run


eval_service = EvalService()
