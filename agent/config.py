from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    router_url: str
    anthropic_api_key: str = ""
    claude_model: str = ""
    claude_max_turns: int = 50
    working_directory: str = "."
    permission_mode: str = "default"
    reconnect_delay_seconds: int = 5
    log_level: str = "INFO"
