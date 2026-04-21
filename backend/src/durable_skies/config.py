from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    temporal_address: str = Field(default="localhost:7233")
    temporal_namespace: str = Field(default="default")

    anthropic_model: str = Field(default="anthropic/claude-sonnet-4-6")
    # Fast model used by summarizer roles (e.g. dispatcher analysts); anthropic_model stays for decision makers.
    anthropic_fast_model: str = Field(default="anthropic/claude-haiku-4-5")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)


@lru_cache
def get_settings() -> Settings:
    # Resolve the repo-root .env lazily: doing this at module import time would
    # trigger RestrictedWorkflowAccessError when the Temporal sandbox validates
    # workflow modules that transitively import this config.
    root = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(root / ".env")
    return Settings()
