"""Centralised application configuration.

All settings are read from environment variables (12-factor style) with safe
local defaults, so the code runs both inside Docker Compose and on a laptop.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Datastores ---
    database_url: str = "postgresql+psycopg://alemeno:alemeno@localhost:5432/alemeno"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- LLM (OpenAI) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_batch_size: int = 20          # transactions per classification call
    llm_max_retries: int = 3          # retries per LLM call (assignment: up to 3)
    llm_backoff_base: float = 2.0     # seconds; exponential backoff base

    # --- Pipeline tuning ---
    # Outlier rule: amount > multiplier * account median.
    anomaly_median_multiplier: float = 3.0
    # Brands that operate only in India; USD on these is flagged.
    domestic_merchants: str = (
        "Swiggy,Ola,IRCTC,Zomato,Jio Recharge,BookMyShow,HDFC ATM,Flipkart"
    )

    # --- Uploads ---
    upload_dir: str = "/app/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    @property
    def domestic_merchant_set(self) -> set[str]:
        return {m.strip().lower() for m in self.domestic_merchants.split(",") if m.strip()}

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
