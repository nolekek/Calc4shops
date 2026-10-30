from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # Telegram bot configuration (optional for standalone browser testing)
    BOT_TOKEN: Optional[str] = None
    WEBAPP_URL: Optional[str] = None
    
    # VPN / Proxy for Telegram Bot API requests
    SOTA_VPN_KEY: Optional[str] = None
    TELEGRAM_PROXY_URL: Optional[str] = None

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./deals.db"

    # Rates
    CBR_API_URL: str = "https://www.cbr-xml-daily.ru/daily_json.js"
    RATES_CACHE_TTL_SECONDS: int = 3600

    # Default business settings
    DEFAULT_TARGET_MARGIN_PCT: float = 20.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_telegram_proxy(self) -> Optional[str]:
        """Возвращает адрес прокси для обращений к Telegram API (если задан в TELEGRAM_PROXY_URL)."""
        if self.TELEGRAM_PROXY_URL:
            return self.TELEGRAM_PROXY_URL
        return None


settings = Settings()
