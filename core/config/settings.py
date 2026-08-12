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


settings = Settings()
