"""Application-wide configuration helpers."""

from __future__ import annotations

import os
from functools import lru_cache, cached_property
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tooling import ToolingConfig


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv()


class AppConfig(BaseSettings):
    """Centralised configuration loaded from environment and config files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    debug: bool = Field(default=False, alias="DEBUG")
    slack_bot_token: str | None = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_app_token: str | None = Field(default=None, alias="SLACK_APP_TOKEN")
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")
    tooling_config_file: Path = Field(
        default=PROJECT_ROOT / "config" / "tooling.toml",
        alias="TOOLING_CONFIG_FILE",
    )

    langfuse_prompt_label: str | None = Field(default=None, alias="LANGFUSE_PROMPT_LABEL")
    langfuse_agent_prompt_name: str | None = Field(
        default=None,
        alias="LANGFUSE_AGENT_PROMPT_NAME",
    )
    langfuse_dm_prompt_name: str | None = Field(
        default=None,
        alias="LANGFUSE_DM_PROMPT_NAME",
    )
    langfuse_inferred_prompt_name: str | None = Field(
        default=None,
        alias="LANGFUSE_INFERRED_PROMPT_NAME",
    )

    @cached_property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @cached_property
    def tooling(self) -> ToolingConfig:
        path = self.tooling_config_file
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return ToolingConfig.from_file(
            path,
            project_root=PROJECT_ROOT,
            base_env=os.environ,
        )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Return the shared ``AppConfig`` instance."""

    return AppConfig()

