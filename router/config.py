from pydantic_settings import BaseSettings, SettingsConfigDict


class RouterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    slack_bot_token: str
    slack_signing_secret: str
    token_expiry_seconds: int = 300
    redis_url: str
    log_level: str = "INFO"
