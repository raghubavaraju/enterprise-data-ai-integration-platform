"""Central configuration.

Every value is sourced from the environment (see ``.env.example``).  Nothing
secret is ever defaulted to a real value: the only defaults present here are
local-development placeholders that are useless outside a laptop.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    platform_mode: str = "local"           # local | cloud
    environment: str = "dev"
    log_level: str = "INFO"
    log_format: str = "json"

    # --- API-led endpoints -------------------------------------------------
    experience_api_port: int = 8080
    store_experience_api_port: int = 8093
    process_api_port: int = 8091
    system_api_port: int = 8090
    data_api_port: int = 8092
    ai_service_port: int = 8087

    crm_system_url: str = "http://localhost:8081"
    order_system_url: str = "http://localhost:8082"
    support_system_url: str = "http://localhost:8083"
    loyalty_system_url: str = "http://localhost:8084"
    catalog_system_url: str = "http://localhost:8085"
    snowflake_data_api_url: str = "http://localhost:8092"
    ai_service_url: str = "http://localhost:8087"
    process_api_url: str = "http://localhost:8091"
    system_api_url: str = "http://localhost:8090"

    # --- Security ----------------------------------------------------------
    oauth_client_id: str = "acme-portal-client"
    oauth_client_secret: str = "change-me-local-only"
    oauth_audience: str = "https://api.acme-retail.example.com"
    oauth_token_ttl_seconds: int = 3600
    jwt_signing_key: str = "local-development-signing-key-not-for-production"

    # --- Policies ----------------------------------------------------------
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_seconds: int = 30
    downstream_timeout_seconds: float = 10.0
    idempotency_ttl_seconds: int = 900
    max_retry_attempts: int = 3
    retry_base_delay_ms: int = 200

    # --- Snowflake ---------------------------------------------------------
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_role: str = "ACME_INTEGRATION_RW"
    snowflake_warehouse: str = "ACME_INTEGRATION_WH"
    snowflake_database: str = "ACME_EDP"
    snowflake_private_key_path: str = ""

    # --- AI ----------------------------------------------------------------
    ai_provider: str = "local"             # local | cortex | openai | bedrock
    ai_model: str = "llama3.1-70b"
    ai_embedding_model: str = "snowflake-arctic-embed-m"
    ai_max_output_tokens: int = 600
    ai_temperature: float = 0.1
    ai_timeout_seconds: float = 20.0
    ai_pii_redaction: bool = True
    ai_human_review_threshold: float = 0.60
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # --- Local warehouse ---------------------------------------------------
    local_warehouse_path: str = "local_warehouse/acme_edp.duckdb"

    correlation_id_header: str = "x-correlation-id"

    @property
    def is_local(self) -> bool:
        return self.platform_mode.lower() == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
