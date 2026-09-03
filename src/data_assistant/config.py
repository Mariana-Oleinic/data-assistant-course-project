"""Application settings with paid integrations disabled by default."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_mode: Literal["offline", "openai"] = "offline"
    allow_paid_llm: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"

    enable_langfuse: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "development"

    database_url: str = (
        "postgresql+psycopg://data_assistant:data_assistant@localhost:5432/data_assistant"
    )

    @model_validator(mode="after")
    def guard_paid_llm(self) -> "Settings":
        if self.llm_mode == "openai":
            if not self.allow_paid_llm:
                raise ValueError(
                    "OpenAI mode is locked. Set ALLOW_PAID_LLM=true explicitly to permit billing."
                )
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OPENAI_API_KEY is required when LLM_MODE=openai.")
        return self

    @property
    def langfuse_enabled(self) -> bool:
        return bool(
            self.enable_langfuse
            and self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_secret_key.get_secret_value().strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
