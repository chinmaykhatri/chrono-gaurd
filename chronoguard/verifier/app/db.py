from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

metadata = sa.MetaData()
json_type = sa.JSON().with_variant(__import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB, "postgresql")


def now():
    return datetime.now(UTC)


def base_columns():
    return [sa.Column("id", sa.String(36), primary_key=True, default=lambda: str(uuid4())), sa.Column("tenant_id", sa.String(128), nullable=False, index=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, default=now)]


requests = sa.Table("requests", metadata, *base_columns(),
    sa.Column("bifrost_request_id", sa.String(256), nullable=False),
    sa.Column("model_id", sa.String(256), nullable=False), sa.Column("provider", sa.String(128)),
    sa.Column("prompt_hash", sa.String(64), nullable=False), sa.Column("messages", json_type),
    sa.Column("policy", sa.String(32), nullable=False), sa.Column("prompt_class", sa.String(32)),
    sa.Column("cache_status", sa.String(32), nullable=False), sa.Column("cache_id", sa.String(256)),
    sa.Column("decision", sa.String(32), nullable=False), sa.Column("decision_detail", json_type, nullable=False, default=dict),
    sa.Column("decision_shadow", sa.String(32)), sa.Column("shadow_reason", sa.Text),
    sa.Column("guard_tripped", sa.Boolean, default=False), sa.Column("guard_reason", sa.String(64)),
    sa.Column("query_signature", sa.Text),
    sa.Column("total_latency_ms", sa.Integer), sa.Column("hook_overhead_us", sa.Integer),
    sa.UniqueConstraint("tenant_id", "bifrost_request_id"), sa.Index("ix_requests_time", "tenant_id", "created_at"))
responses = sa.Table("responses", metadata, *base_columns(),
    sa.Column("request_id", sa.String(36), sa.ForeignKey("requests.id", ondelete="CASCADE"), nullable=False),
    sa.Column("origin", sa.String(32), nullable=False), sa.Column("content", sa.Text),
    sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("model_id", sa.String(256), nullable=False),
    sa.Column("input_tokens", sa.Integer), sa.Column("output_tokens", sa.Integer),
    sa.Column("annotation_status", sa.String(32), nullable=False, default="pending"),
    sa.Column("annotation", json_type, nullable=False, default=dict),
    sa.UniqueConstraint("tenant_id", "request_id"))
facts = sa.Table("facts", metadata, *base_columns(),
    sa.Column("fact_key", sa.String(768), nullable=False), sa.Column("fact_hash", sa.String(64), nullable=False),
    sa.Column("class_key", sa.String(32), nullable=False), sa.Column("entity", sa.String(200), nullable=False),
    sa.Column("attribute", sa.String(128), nullable=False), sa.Column("qualifier", sa.String(200)),
    sa.Column("current_value", sa.Text), sa.Column("last_verdict", sa.String(32)),
    sa.Column("fresh_until", sa.DateTime(timezone=True)), sa.Column("last_verified_at", sa.DateTime(timezone=True)),
    sa.Column("interval_seconds", sa.Integer), sa.Column("revision", sa.Integer, nullable=False, default=0),
    sa.Column("source_urls", json_type), sa.Column("source_text_hash", sa.String(64)),
    sa.Column("window_hash", sa.String(64)), sa.Column("last_extracted_at", sa.DateTime(timezone=True)),
    sa.Column("delta_confirmed", sa.Boolean, default=False), sa.Column("delta_saved_credits", sa.Float, default=0.0),
    sa.Column("ledger", json_type, nullable=False, default=dict),
    sa.UniqueConstraint("tenant_id", "fact_key"), sa.UniqueConstraint("tenant_id", "fact_hash"))
claims = sa.Table("claims", metadata, *base_columns(),
    sa.Column("response_id", sa.String(36), sa.ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("fact_id", sa.String(36), sa.ForeignKey("facts.id")), sa.Column("cache_id", sa.String(256)),
    sa.Column("text", sa.Text), sa.Column("entity", sa.String(200)), sa.Column("attribute", sa.String(128)),
    sa.Column("stated_value", sa.Text), sa.Column("class_key", sa.String(32)),
    sa.Column("status", sa.String(32), nullable=False), sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("source_urls", json_type), sa.Column("source_text_hash", sa.String(64)),
    sa.Column("delta_confirmed", sa.Boolean, default=False),
    sa.Column("claim_data", json_type, nullable=False), sa.Column("annotation", json_type, nullable=False, default=dict),
    sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("response_id", "ordinal"), sa.Index("ix_claim_fact", "tenant_id", "fact_id"))
verifications = sa.Table("verifications", metadata, *base_columns(),
    sa.Column("fact_id", sa.String(36), sa.ForeignKey("facts.id"), nullable=False),
    sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id", ondelete="SET NULL")),
    sa.Column("trigger_kind", sa.String(32), nullable=False), sa.Column("verdict", sa.String(32)),
    sa.Column("effective_verdict", sa.String(32)), sa.Column("status", sa.String(32), nullable=False),
    sa.Column("corrected_value", sa.Text), sa.Column("rationale", sa.String(280)),
    sa.Column("judge_confidence", sa.Float), sa.Column("freshness", sa.Float), sa.Column("support_confidence", sa.Float),
    sa.Column("features", json_type), sa.Column("queries", json_type), sa.Column("latency_ms", sa.Integer),
    sa.Column("tavily_credits", sa.Float), sa.Column("finished_at", sa.DateTime(timezone=True)))
evidence = sa.Table("evidence", metadata, *base_columns(),
    sa.Column("verification_id", sa.String(36), sa.ForeignKey("verifications.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.Text, nullable=False), sa.Column("domain", sa.String(253), nullable=False),
    sa.Column("title", sa.String(500)), sa.Column("snippet", sa.String(600)), sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False), sa.Column("authority_tier", sa.Integer, nullable=False),
    sa.Column("source", sa.String(32), nullable=False), sa.Column("label", sa.String(32)))
cache_entries = sa.Table("cache_entries", metadata, *base_columns(),
    sa.Column("bifrost_cache_id", sa.String(256), nullable=False),
    sa.Column("response_id", sa.String(36), sa.ForeignKey("responses.id", ondelete="SET NULL")),
    sa.Column("status", sa.String(32), nullable=False), sa.Column("best_before", sa.DateTime(timezone=True)),
    sa.Column("hard_expiry", sa.DateTime(timezone=True)), sa.Column("manifest_rev", sa.Integer, nullable=False, default=0),
    sa.Column("manifest", json_type, nullable=False), sa.Column("pinned", sa.Boolean, nullable=False, default=False),
    sa.Column("hits_24h", sa.Integer, nullable=False, default=0), sa.Column("supersedes_entry_id", sa.String(36)),
    sa.UniqueConstraint("tenant_id", "bifrost_cache_id"), sa.Index("ix_cache_status", "tenant_id", "status", "best_before"))
policies = sa.Table("policies", metadata, *base_columns(), sa.Column("name", sa.String(32), nullable=False),
    sa.Column("config", json_type, nullable=False), sa.UniqueConstraint("tenant_id", "name"))
settings_table = sa.Table("settings", metadata, *base_columns(), sa.Column("key", sa.String(128), nullable=False),
    sa.Column("value", json_type, nullable=False), sa.UniqueConstraint("tenant_id", "key"))
events = sa.Table("events", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, default=now),
    sa.Column("type", sa.String(64), nullable=False), sa.Column("payload", json_type, nullable=False),
    sa.Index("ix_events_tenant_id", "tenant_id", "id"))
cost_ledger = sa.Table("cost_ledger", metadata, *base_columns(), sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("units", sa.Float, nullable=False), sa.Column("unit_label", sa.String(32), nullable=False),
    sa.Column("usd", sa.Float), sa.Column("model_id", sa.String(256)), sa.Column("class_key", sa.String(32)),
    sa.Column("request_id", sa.String(36)), sa.Column("verification_id", sa.String(36)))
jobs = sa.Table("verification_jobs", metadata, *base_columns(),
    sa.Column("response_id", sa.String(36), sa.ForeignKey("responses.id", ondelete="CASCADE"), nullable=False),
    sa.Column("state", sa.String(32), nullable=False, default="queued"), sa.Column("payload", json_type),
    sa.Column("attempts", sa.Integer, nullable=False, default=0), sa.Column("error_code", sa.String(64)),
    sa.Column("locked_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("tenant_id", "response_id"))


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True, echo=False)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def healthy(self):
        async with self.engine.connect() as connection:
            await connection.execute(sa.text("SELECT 1"))
        return True

    async def close(self):
        await self.engine.dispose()
