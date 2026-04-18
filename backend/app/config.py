from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # Диплом/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://nutriagent:nutriagent@localhost:5433/nutriagent"
    REDIS_URL: str = "redis://localhost:6379/0"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL_NAME: str = "openai/gpt-4o"
    LLM_TIMEOUT_SEC: int = 60
    LLM_MAX_OUTPUT_TOKENS: int = 1200
    LLM_MAX_RETRIES: int = 4
    LLM_CONTEXT_RECIPE_LIMIT: int = 18
    AGENT_CLI_MIN_CONTEXT_RECIPE_LIMIT: int = 32
    LLM_RETRY_HISTORY_LIMIT: int = 1
    LLM_RETRY_RESPONSE_PREVIEW_CHARS: int = 600
    CATALOG_SOURCE_FETCH_TIMEOUT_SEC: int = 20
    CATALOG_SOURCE_MAX_BYTES: int = 60000
    CATALOG_SOURCE_TEXT_CHAR_LIMIT: int = 6000
    CATALOG_ALLOWED_SOURCE_DOMAINS: str = ""
    SECRET_KEY: str = "change-me"
    DEBUG: bool = False

    @property
    def database_url_sync(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "")


settings = Settings()
