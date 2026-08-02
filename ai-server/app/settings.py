from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "jobiss-ai-server"
    environment: str = "local"
    shared_secret: str = "local-ai-secret"
    analysis_provider: str = "unconfigured"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    claude_cli_model: str = "sonnet"
    request_timeout_seconds: float = 600.0
    progress_log_interval_seconds: float = 10.0
    max_concurrency: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JOBISS_AI_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.environment.lower() not in {"prod", "production"}:
            return self
        if len(self.shared_secret.encode("utf-8")) < 32:
            raise ValueError("Production AI shared secret must contain at least 32 bytes")
        if self.analysis_provider == "unconfigured":
            raise ValueError("Production requires an AI analysis provider")
        if self.analysis_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("Production Anthropic provider requires an API key")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
