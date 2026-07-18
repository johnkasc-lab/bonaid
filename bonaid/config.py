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
    alerts_enabled: bool = True  # master switch - set false in .env to silence all notifications without unsetting credentials

    # --- Broker / market data (used by later phases) ---
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True

    # --- Risk management (used by the Risk Agent) ---
    default_capital: float = 100_000.0       # simulated account size until real broker/portfolio integration exists
    risk_per_trade_pct: float = 1.0          # % of capital risked per trade (distance to stop-loss)
    reward_risk_ratio: float = 2.0           # take-profit distance = stop distance * this ratio
    max_position_pct: float = 10.0           # hard cap: no single position exceeds this % of capital
    atr_stop_multiplier: float = 2.0         # stop-loss = entry price -/+ (ATR * this multiplier)
    max_total_exposure_pct: float = 50.0     # Portfolio Agent flags if aggregate implied exposure exceeds this
    max_sector_exposure_pct: float = 25.0    # flags if any single sector's positions exceed this % of capital
    max_portfolio_drawdown_pct: float = 15.0 # alert (and optionally auto-close) if TOTAL unrealized P&L drops below -this% of capital
    auto_close_on_drawdown: bool = False     # if True, breaching max_portfolio_drawdown_pct auto-closes ALL open positions (a real kill switch - off by default, this is a bigger action than opening a single position)

    # --- LLM narration (OFF by default) ---
    # qwen2.5:0.5b (and even 1.5b) have been observed fabricating events and
    # mislabeling sentiment polarity that isn't in the source headlines -
    # e.g. describing a securities fraud lawsuit as "positive news". The
    # structured data (action/confidence/sentiment scores) never depends on
    # the LLM and is unaffected. Narration is opt-in until spot-checked
    # against a stronger model. Override via .env: ENABLE_LLM_NARRATION=true
    enable_llm_narration: bool = False

    # --- Reddit OAuth (used by the Sentiment Agent) ---
    # Reddit's public .json endpoints now block most unauthenticated
    # traffic (403, serving the normal web page instead of JSON). A free
    # "script" app (https://www.reddit.com/prefs/apps) is the officially
    # supported, still-free way around this - 100 requests/min is far more
    # than this agent needs. Leave both unset to have Sentiment Agent
    # gracefully report "not configured" instead of attempting doomed
    # unauthenticated requests.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_username: str | None = None  # Reddit's API rules want a real account referenced in the
                                          # User-Agent, not a placeholder - improves compliance/reliability

    # --- FRED (macro/economic data, used by the Macro Agent) ---
    # Free, no-cost API key from https://fred.stlouisfed.org/docs/api/api_key.html
    fred_api_key: str | None = None


settings = Settings()
