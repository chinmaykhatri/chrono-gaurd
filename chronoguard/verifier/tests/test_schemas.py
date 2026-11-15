import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.schemas.contracts import Ingest, Claim, Category, Verdict, Policy, POLICIES

def test_ingest_valid():
    ing = Ingest(
        request_id="req-123",
        model_id="gpt-4o",
        response_text="The latest Python is 3.12.",
        prompt_class=Category.SOFTWARE,
        policy="strict",
    )
    assert ing.request_id == "req-123"
    assert ing.policy == "strict"
    assert ing.prompt_class == Category.SOFTWARE

def test_ingest_disallow_naive_datetime():
    with pytest.raises(ValidationError):
        Ingest(
            request_id="req-123",
            model_id="gpt-4o",
            response_text="Hello",
            now=datetime(2026, 1, 1, 12, 0),  # Naive, no tzinfo
        )

def test_claim_validation():
    c = Claim(
        text="FastAPI version 0.115.0",
        entity="FastAPI",
        attribute="version",
        stated_value="0.115.0",
        class_key=Category.SOFTWARE,
        importance=0.9,
    )
    assert c.entity == "FastAPI"
    assert c.importance == 0.9

def test_claim_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Claim(
            text="Test",
            entity="Test",
            attribute="attr",
            stated_value="val",
            class_key=Category.SOFTWARE,
            unknown_extra_field="error",
        )

def test_default_policies():
    assert "strict" in POLICIES
    assert "standard" in POLICIES
    assert "lenient" in POLICIES
    strict = POLICIES["strict"]
    assert strict.strictness == "strict"
    assert strict.on_unverifiable == "fail_closed"
    assert strict.serve_min_freshness == 80

