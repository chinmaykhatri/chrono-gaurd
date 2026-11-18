from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CG_", env_file=".env", env_file_encoding="utf-8", extra="ignore")
    environment: Literal["development", "production", "test"] = "production"
    database_url: SecretStr = SecretStr("postgresql+asyncpg://chronoguard@postgres/chronoguard")
    redis_url: SecretStr = SecretStr("redis://redis:6379/0")
    internal_key: SecretStr
    admin_password_hash: SecretStr
    session_secret: SecretStr
    console_origin: str = "https://localhost"
    tenant_id: str = "default"
    session_ttl_seconds: int = Field(3600, ge=60, le=86400)
    bifrost_url: str = "http://bifrost:8080"
    bifrost_api_key: SecretStr = SecretStr("")
    extractor_model: str = ""
    judge_model: str = ""
    judge_escalation_model: str = ""
    tavily_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("CG_TAVILY_API_KEY", "TAVILY_API_KEY"))
    store_content: bool = False
    retention_days: int = Field(7, ge=1, le=365)
    allow_simulated_clock: bool = False
    request_limit_bytes: int = Field(131072, ge=4096, le=1048576)
    queue_size: int = Field(2000, ge=1, le=10000)
    workers: int = Field(4, ge=1, le=32)
    tavily_credits_per_hour: int = Field(300, ge=1)
    llm_tokens_per_hour: int = Field(400000, ge=1000)
    source_authorities: dict[str, int] = Field(default_factory=dict)
    source_denylist: list[str] = Field(default_factory=list)
    shadow_enabled: bool = Field(False)
    guard_enabled: bool = Field(False)
    delta_enabled: bool = Field(False)
    scheduler_mode: str = Field("standard")
    scheduler_budget_checks_per_hour: int = Field(100)
    # Model knowledge cutoffs, ISO dates keyed by the model id used through
    # Bifrost. An unknown model is treated as 18 months old, never as current.
    model_cutoffs: dict[str, str] = Field(default_factory=dict)
    bifrost_version: str = "1.15.2"

    @model_validator(mode="after")
    def secure_configuration(self):
        if len(self.internal_key.get_secret_value()) < 32 or len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("Internal and session secrets must each contain at least 32 characters")
        if not self.admin_password_hash.get_secret_value().startswith("$argon2id$"):
            raise ValueError("Admin password must be an Argon2id hash")
        origin = urlsplit(self.console_origin)
        if origin.scheme not in ("http", "https") or not origin.netloc or origin.path not in ("", "/") or origin.query or origin.fragment or origin.username:
            raise ValueError("Console origin must be an HTTP(S) origin")
        if self.environment == "production" and origin.scheme != "https":
            raise ValueError("Production requires an HTTPS console origin")
        if any(tier not in (1, 2, 3, 4) for tier in self.source_authorities.values()):
            raise ValueError("Authority tiers must be 1 through 4")
        return self
