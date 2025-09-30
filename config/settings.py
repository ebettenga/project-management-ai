"""Application-wide configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tooling import ToolingConfig


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv()


@dataclass(frozen=True)
class SlackOAuthConfig:
    signing_secret: str | None
    client_id: str | None
    client_secret: str | None


@dataclass(frozen=True)
class MemoryConfig:
    collection: str
    dense_vector_name: str
    sparse_vector_name: str
    embedding_model: str
    llm_model: str
    openai_api_key: str | None
    qdrant_host: str
    qdrant_http_port: int


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


class GoogleWorkspaceSettings:
    """Adapter around Google Workspace environment configuration."""

    def __init__(self, parent: "AppConfig") -> None:
        self._parent = parent
        self._single_user_override: bool | None = None

        if self.stateless_mode and not self.oauth21_enabled:
            raise ValueError(
                "WORKSPACE_MCP_STATELESS_MODE requires MCP_ENABLE_OAUTH21 to be enabled"
            )

    @property
    def port(self) -> int:
        return self._parent.port_override or self._parent.workspace_mcp_port

    @property
    def base_uri(self) -> str:
        return self._parent.workspace_mcp_base_uri

    @property
    def base_url(self) -> str:
        return f"{self.base_uri}:{self.port}"

    @property
    def external_url(self) -> str | None:
        return self._parent.workspace_external_url

    @property
    def oauth_base_url(self) -> str:
        return self.external_url or self.base_url

    @property
    def client_id(self) -> str | None:
        return self._parent.google_oauth_client_id

    @property
    def client_secret(self) -> str | None:
        return self._parent.google_oauth_client_secret

    @property
    def client_secret_redacted(self) -> str:
        secret = self.client_secret or "Not Set"
        if len(secret) <= 8:
            return "Invalid or too short"
        return f"{secret[:4]}...{secret[-4:]}"

    @property
    def oauth21_enabled(self) -> bool:
        return self._parent.mcp_enable_oauth21

    @property
    def stateless_mode(self) -> bool:
        return self._parent.workspace_mcp_stateless_mode

    @property
    def oauthlib_insecure_transport(self) -> bool:
        return self._parent.oauthlib_insecure_transport

    @property
    def redirect_uri(self) -> str:
        return self._parent.google_oauth_redirect_uri or f"{self.base_url}/oauth2callback"

    @property
    def custom_redirect_uris(self) -> tuple[str, ...]:
        return _split_csv(self._parent.oauth_custom_redirect_uris)

    @property
    def all_redirect_uris(self) -> tuple[str, ...]:
        uris: tuple[str, ...] = (self.redirect_uri,)
        if self.custom_redirect_uris:
            uris = uris + tuple(x for x in self.custom_redirect_uris if x not in uris)
        return uris

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        defaults: tuple[str, ...] = (
            self.base_url,
            "vscode-webview://",
            "https://vscode.dev",
            "https://github.dev",
        )
        extra = tuple(x for x in _split_csv(self._parent.oauth_allowed_origins) if x)
        combined: list[str] = []
        for origin in defaults + extra:
            if origin not in combined:
                combined.append(origin)
        return tuple(combined)

    @property
    def google_client_secret_path(self) -> str | None:
        return self._parent.google_client_secret_path

    @property
    def google_credentials_dir(self) -> str | None:
        return self._parent.google_mcp_credentials_dir

    @property
    def google_pse_api_key(self) -> str | None:
        return self._parent.google_pse_api_key

    @property
    def google_pse_engine_id(self) -> str | None:
        return self._parent.google_pse_engine_id

    @property
    def user_google_email(self) -> str | None:
        if self.oauth21_enabled:
            return None
        return self._parent.user_google_email

    @property
    def single_user_mode(self) -> bool:
        if self._single_user_override is not None:
            return self._single_user_override
        return self._parent.mcp_single_user_mode

    def enable_single_user_mode(self) -> None:
        self._single_user_override = True

    def disable_single_user_mode(self) -> None:
        self._single_user_override = False


class AppConfig(BaseSettings):
    """Centralised configuration loaded from environment and config files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    debug: bool = Field(default=False, alias="DEBUG")

    # Slack configuration
    slack_bot_token: str | None = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_app_token: str | None = Field(default=None, alias="SLACK_APP_TOKEN")
    slack_signing_secret: str | None = Field(default=None, alias="SLACK_SIGNING_SECRET")
    slack_client_id: str | None = Field(default=None, alias="SLACK_CLIENT_ID")
    slack_client_secret: str | None = Field(default=None, alias="SLACK_CLIENT_SECRET")

    # Database
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")

    # Tooling config file
    tooling_config_file: Path = Field(
        default=PROJECT_ROOT / "config" / "tooling.toml",
        alias="TOOLING_CONFIG_FILE",
    )

    # Langfuse prompts
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

    # Provider keys
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    vertex_ai_project_id: str | None = Field(default=None, alias="VERTEX_AI_PROJECT_ID")
    vertex_ai_location: str | None = Field(default=None, alias="VERTEX_AI_LOCATION")

    # Memory service configuration
    memory_collection: str = Field(default="memories", alias="MEMORY_COLLECTION")
    memory_dense_vector_name: str = Field(
        default="dense", alias="MEMORY_DENSE_VECTOR_NAME"
    )
    memory_sparse_vector_name: str = Field(
        default="bm25", alias="MEMORY_SPARSE_VECTOR_NAME"
    )
    memory_embedding_model: str = Field(
        default="text-embedding-3-small", alias="MEMORY_EMBEDDING_MODEL"
    )
    memory_llm_model: str = Field(default="gpt-4.1-mini", alias="MEMORY_LLM_MODEL")
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_http_port: int = Field(default=6333, alias="QDRANT_HTTP_PORT")

    # Google Workspace MCP configuration
    port_override: int | None = Field(default=None, alias="PORT")
    workspace_mcp_port: int = Field(default=8000, alias="WORKSPACE_MCP_PORT")
    workspace_mcp_base_uri: str = Field(
        default="http://localhost", alias="WORKSPACE_MCP_BASE_URI"
    )
    workspace_external_url: str | None = Field(
        default=None, alias="WORKSPACE_EXTERNAL_URL"
    )
    google_oauth_client_id: str | None = Field(
        default=None, alias="GOOGLE_OAUTH_CLIENT_ID"
    )
    google_oauth_client_secret: str | None = Field(
        default=None, alias="GOOGLE_OAUTH_CLIENT_SECRET"
    )
    google_oauth_redirect_uri: str | None = Field(
        default=None, alias="GOOGLE_OAUTH_REDIRECT_URI"
    )
    oauth_custom_redirect_uris: str | None = Field(
        default=None, alias="OAUTH_CUSTOM_REDIRECT_URIS"
    )
    oauth_allowed_origins: str | None = Field(
        default=None, alias="OAUTH_ALLOWED_ORIGINS"
    )
    user_google_email: str | None = Field(default=None, alias="USER_GOOGLE_EMAIL")
    mcp_single_user_mode: bool = Field(default=False, alias="MCP_SINGLE_USER_MODE")
    mcp_enable_oauth21: bool = Field(default=False, alias="MCP_ENABLE_OAUTH21")
    workspace_mcp_stateless_mode: bool = Field(
        default=False, alias="WORKSPACE_MCP_STATELESS_MODE"
    )
    oauthlib_insecure_transport: bool = Field(
        default=False, alias="OAUTHLIB_INSECURE_TRANSPORT"
    )
    google_client_secret_path: str | None = Field(
        default=None, alias="GOOGLE_CLIENT_SECRET_PATH"
    )
    google_mcp_credentials_dir: str | None = Field(
        default=None, alias="GOOGLE_MCP_CREDENTIALS_DIR"
    )
    google_pse_api_key: str | None = Field(default=None, alias="GOOGLE_PSE_API_KEY")
    google_pse_engine_id: str | None = Field(default=None, alias="GOOGLE_PSE_ENGINE_ID")

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
        )

    @cached_property
    def slack_oauth(self) -> SlackOAuthConfig:
        return SlackOAuthConfig(
            signing_secret=self.slack_signing_secret,
            client_id=self.slack_client_id,
            client_secret=self.slack_client_secret,
        )

    @cached_property
    def memory(self) -> MemoryConfig:
        return MemoryConfig(
            collection=self.memory_collection,
            dense_vector_name=self.memory_dense_vector_name,
            sparse_vector_name=self.memory_sparse_vector_name,
            embedding_model=self.memory_embedding_model,
            llm_model=self.memory_llm_model,
            openai_api_key=self.openai_api_key,
            qdrant_host=self.qdrant_host,
            qdrant_http_port=self.qdrant_http_port,
        )

    @cached_property
    def google_workspace(self) -> GoogleWorkspaceSettings:
        return GoogleWorkspaceSettings(self)


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Return the shared ``AppConfig`` instance."""

    return AppConfig()


def iter_custom_redirects(settings: AppConfig) -> Iterable[str]:
    """Helper for testing: iterate custom redirect URIs."""

    return settings.google_workspace.custom_redirect_uris

