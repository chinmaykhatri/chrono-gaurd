from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Category(StrEnum):
    STATIC = "static"
    SLOW = "slow_facts"
    PEOPLE = "org_people"
    SOFTWARE = "software_versions"
    PRICING = "pricing_plans"
    REGULATION = "regulation_policy"
    NEWS = "news_events"
    REALTIME = "realtime"


class Message(Contract):
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(max_length=12000)


class Usage(Contract):
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)


class Ingest(Contract):
    tenant_id: str = Field("default", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:-]+$")
    request_id: str = Field(min_length=1, max_length=256)
    cache_id: str | None = Field(None, max_length=256)
    origin: Literal["provider", "legacy_cache", "regenerated", "guard_bypassed"] = "provider"
    model_id: str = Field(min_length=1, max_length=256)
    provider: str = Field("", max_length=128)
    messages: list[Message] = Field(default_factory=list, max_length=6)
    prompt_text: str | None = None
    query_signature: str | None = None
    response_text: str = Field(min_length=1, max_length=12000)
    usage: Usage = Field(default_factory=Usage)
    prompt_class: Category = Category.SLOW
    policy: Literal["strict", "standard", "lenient"] = "standard"
    decision_shadow: str | None = Field(None, max_length=32)
    shadow_reason: str | None = None
    guard_tripped: bool = False
    guard_reason: str | None = None
    now: datetime | None = None
    deadline_ms: int = Field(4500, ge=100, le=30000)
    chat: dict | None = None

    @field_validator("tenant_id", mode="before")
    @classmethod
    def default_tenant(cls, value):
        if not value:
            return "default"
        return value

    @field_validator("now")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("timestamp must include timezone")
        return value


class Claim(Contract):
    text: str = Field(min_length=1, max_length=2000)
    span: tuple[int, int] | None = None
    claim_type: Literal["fact", "opinion", "procedure", "definition", "personal"] = "fact"
    entity: str = Field(max_length=200)
    entity_type: Literal["org", "person_public", "person_private", "product", "software", "law", "place", "event", "other"] = "other"
    attribute: str = Field(min_length=1, max_length=128)
    stated_value: str = Field(max_length=1000)
    qualifier: str | None = Field(None, max_length=200)
    class_key: Category
    importance: float = Field(0.5, ge=0, le=1)
    as_of_hint: date | None = None
    official_domain_hint: str | None = Field(None, max_length=253)


class Extraction(Contract):
    claims: list[Claim] = Field(max_length=25)


class Evidence(Contract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    url: str
    domain: str
    title: str = Field("", max_length=500)
    snippet: str = Field("", max_length=600)
    published_at: datetime | None = None
    retrieved_at: datetime
    tier: int = Field(4, ge=1, le=4)
    source: Literal["tavily_search", "tavily_extract"] = "tavily_search"
    score: float | None = Field(None, ge=0, le=1)


class Verdict(Contract):
    verdict: Literal["confirmed", "outdated", "contradicted", "unverifiable"]
    corrected_value: str | None = Field(None, max_length=1000)
    confidence: float | None = Field(None, ge=0, le=1)
    support_ids: list[str] = Field(default_factory=list, max_length=6)
    contradict_ids: list[str] = Field(default_factory=list, max_length=6)
    as_of_note: str = Field("", max_length=280)
    rationale: str = Field("", max_length=280)


class Policy(Contract):
    name: Literal["strict", "standard", "lenient"]
    strictness: Literal["strict", "standard", "lenient"]
    mode: Literal["async", "verify_before_return"]
    blocking_budget_ms: int = Field(4500, ge=100, le=30000)
    revalidate_budget_ms: int = Field(3000, ge=100, le=30000)
    regen_budget_ms: int = Field(12000, ge=100, le=60000)
    serve_min_freshness: int = Field(60, ge=0, le=100)
    evict_below: int = Field(35, ge=0, le=100)
    on_unverifiable: Literal["serve_annotated", "fail_closed"] = "serve_annotated"
    regen_on_stale: bool = True
    max_claims_per_response: int = Field(8, ge=1, le=25)
    max_credits_per_response: float = Field(6, ge=0, le=100)


POLICIES = {
    "strict": Policy(name="strict", strictness="strict", mode="verify_before_return", serve_min_freshness=80, evict_below=50, on_unverifiable="fail_closed", max_claims_per_response=6),
    "standard": Policy(name="standard", strictness="standard", mode="async"),
    "lenient": Policy(name="lenient", strictness="lenient", mode="async", serve_min_freshness=40, evict_below=20, regen_on_stale=False, max_claims_per_response=10, max_credits_per_response=4),
}


class Revalidate(Contract):
    tenant_id: str = Field("default", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:-]+$")
    cache_id: str = Field(min_length=1, max_length=256)
    policy: Literal["strict", "standard", "lenient"] = "standard"
    deadline_ms: int = Field(3000, ge=100, le=60000)
    reason: Literal["due", "stale", "unverified", "manual", "swr", "blocking_revalidation", "evict_regen", "lazy_eviction", "guard_bypass"] = "due"
    force: bool = False
    chat: dict | None = None


class RecordHit(Contract):
    tenant_id: str = Field("default", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:-]+$")
    request_id: str = Field(min_length=1, max_length=256)
    cache_id: str = Field(min_length=1, max_length=256)
    origin: Literal["provider", "legacy_cache", "regenerated", "guard_bypassed"] = "legacy_cache"
    model_id: str = Field(default="configured", max_length=256)
    policy: Literal["strict", "standard", "lenient"] = "standard"
    prompt_class: Category = Category.SLOW
    cache_status: Literal["hit", "hit_direct", "hit_semantic"] = "hit"
    decision: str = "serve"
    decision_shadow: str | None = None
    shadow_reason: str | None = None
    guard_tripped: bool = False
    guard_reason: str | None = None
    query_signature: str | None = None
    prompt_text: str | None = None
    latency_ms: int = Field(default=1, ge=0)

    @field_validator("tenant_id", mode="before")
    @classmethod
    def default_tenant(cls, value):
        if not value:
            return "default"
        return value
