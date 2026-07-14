"""
bonaid/config.py
Single source of truth for all configuration. Every other module imports
`settings` from here rather than reading os.environ directly - this is what
makes the whole system testable and lets Docker Compose inject config
via environment variables cleanly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Bonaid"
    environment: str = Field(default="development")  # development | production
    log_level: str = Field(default="INFO")

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bonaid"
    postgres_user: str = "bonaid"
    postgres_password: str = "bonaid_dev_password"

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # --- Ollama (local LLM) ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "deepseek-r1:7b"  # swap to qwen2.5:7b etc as needed

    # --- Notifications (used by later phases) ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_pass: str | None = None
    alert_email_to: str | None = None

    # --- Broker / market data (used by later phases) ---
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True


settings = Settings()
