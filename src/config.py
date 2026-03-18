"""Configuration management using Pydantic Settings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Slack Configuration
    slack_bot_token: str = Field(
        description="Slack Bot Token (xoxb-...)"
    )
    slack_app_token: str = Field(
        description="Slack App-Level Token (xapp-...) for Socket Mode"
    )
    slack_signing_secret: str = Field(
        default="",
        description="Slack Signing Secret (optional for Socket Mode)"
    )

    # Claude Configuration
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API Key (optional if using default auth)"
    )
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use"
    )
    claude_max_turns: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum conversation turns"
    )

    # Permission mode: controls what tools Claude can use without asking
    # - "default": Use Claude's default permissions from settings files
    # - "bypass": All tools run without permission checks (use in sandboxed environments)
    # - "allowEdits": Auto-approve file edits, Bash commands are blocked
    # - "plan": Read-only mode, no writes or bash allowed
    permission_mode: Literal["default", "bypass", "allowEdits", "plan"] = Field(
        default="default",
        description="Default permission mode for Claude tool use"
    )

    # Session Configuration
    session_storage: Literal["memory", "redis"] = Field(
        default="memory",
        description="Session storage backend"
    )
    session_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="Session time-to-live in seconds"
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for session storage"
    )

    # Working Directory
    working_directory: str = Field(
        default=".",
        description="Working directory for Claude operations"
    )

    # Session Connection
    claude_session_file: str = Field(
        default="/tmp/current_claude_session.txt",
        description="Path to file containing the current Claude terminal session ID (written by SessionStart hook)"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )


# Global settings instance (lazy loaded)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
