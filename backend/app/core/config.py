"""
Application configuration via environment variables / .env

ASSESSMENT NOTES — Tunables & operational defaults live here.
"""
from functools import lru_cache
from pydantic import Field, model_validator
from typing import Literal
from uuid import uuid4
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "MarTech Intelligence Platform"
    DEBUG: bool = False
    APP_ENV: Literal["development", "production", "test"] = "development"
    API_KEY: str = ""
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    AUTO_CREATE_TABLES: bool = False
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/martech"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/martech"

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_STREAM: str = "events:stream"
    REDIS_IDEMPOTENCY_SET: str = "events:seen"
    REDIS_FREQ_CAP_PREFIX: str = "freqcap:"
    REDIS_CONSUMER_GROUP: str = "event-workers"
    REDIS_CONSUMER_NAME: str = Field(default_factory=lambda: f"worker-{uuid4().hex[:12]}")
    WORKER_CLAIM_IDLE_MS: int = Field(60000, ge=1000)
    WORKER_HEARTBEAT_TTL: int = Field(120, ge=30)
    OUTBOX_RETENTION_DAYS: int = Field(7, ge=1)
    OUTBOX_BATCH_SIZE: int = Field(500, ge=1, le=5000)

    SCORE_DECAY_LAMBDA: float = 0.05

    WORKER_MAX_RETRIES: int = 3
    WORKER_BASE_BACKOFF_SEC: float = 2.0
    WORKER_BATCH_SIZE: int = 10
    WORKER_BLOCK_MS: int = 5000

    # LLM: "openrouter" | "langchain" | "groq" | "ollama" | "none"
    LLM_PROVIDER: str = "openrouter"
    # OpenRouter (primary for SaaS demo)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_SITE_NAME: str = "MarTech Intelligence"
    # Groq (optional legacy)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    # Ollama (local)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    LLM_TIMEOUT_SEC: float = 30.0
    LLM_CIRCUIT_BREAKER_THRESHOLD: int = Field(3, ge=1)
    LLM_CIRCUIT_BREAKER_COOLDOWN_SEC: float = Field(60.0, gt=0)

    RATE_LIMIT_EVENTS_PER_MIN: int = Field(600, ge=1)

    # true = worker inside API process (demo); false = run `python -m app.workers` separately
    RUN_EMBEDDED_WORKER: bool = True

    @model_validator(mode="after")
    def production_security(self):
        if self.APP_ENV == "production":
            if len(self.API_KEY) < 32:
                raise ValueError("Production requires an API_KEY of at least 32 characters")
            if "*" in self.CORS_ORIGINS or self.AUTO_CREATE_TABLES:
                raise ValueError("Production requires explicit CORS origins and migrations")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
