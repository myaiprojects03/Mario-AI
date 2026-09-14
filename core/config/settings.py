from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration settings loaded via pydantic-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = ""
    JARBET_API_KEY: str = ""
    JARBET_BASE_URL: str = ""
    BETSAPI_TOKEN: str = ""

    # Provisional Daily Tip Limits per Channel
    DAILY_LIMIT_FIFA_GOALS_OU: int = 150
    DAILY_LIMIT_FIFA_MONEY_LINE: int = 150
    DAILY_LIMIT_FIFA_ASIAN_HANDICAP: int = 100
    DAILY_LIMIT_EBASKET_MONEY_LINE: int = 150
    DAILY_LIMIT_EBASKET_OU: int = 150


settings = Settings()
