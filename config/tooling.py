"""Typed tooling configuration for MCP servers and tool approvals."""

from __future__ import annotations

import tomllib
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class ToolApprovalSettings(BaseModel):
    """Approval metadata for wrapping tools with user confirmation."""

    summary: str
    context: str
    allow_edit: bool = True
    allow_reject: bool = True


class MCPServerSettings(BaseModel):
    """Definition of an MCP server endpoint."""

    transport: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    def as_client_config(
        self,
        *,
        project_root: Path,
    ) -> dict[str, Any]:
        """Materialise a configuration dict suitable for ``MultiServerMCPClient``."""

        config: dict[str, Any] = {"transport": self.transport}

        if self.command:
            config["command"] = self._expand(self.command, project_root)
        if self.args:
            config["args"] = [self._expand(arg, project_root) for arg in self.args]
        if self.url:
            config["url"] = self._expand(self.url, project_root)

        if self.env:
            config["env"] = {
                key: self._expand(value, project_root)
                for key, value in self.env.items()
            }

        extra = getattr(self, "model_extra", None) or {}
        for key, value in extra.items():
            config[key] = value

        return config

    @staticmethod
    def _expand(value: str, project_root: Path) -> str:
        if "{project_root}" in value:
            return value.replace("{project_root}", str(project_root))
        return value


class ServersSection(BaseModel):
    """Grouping of shared and optional MCP servers."""

    base: dict[str, MCPServerSettings] = Field(default_factory=dict)
    platforms: dict[str, MCPServerSettings] = Field(default_factory=dict)


class AgentSection(BaseModel):
    """Agent-centric defaults defined in tooling config."""

    model: str = "openai:gpt-4.1"


class ToolingFileModel(BaseModel):
    """Raw structure of the ``tooling.toml`` declaration."""

    agent: AgentSection = Field(default_factory=AgentSection)
    servers: ServersSection = Field(default_factory=ServersSection)
    tool_approvals: dict[str, ToolApprovalSettings] = Field(default_factory=dict)


class ToolingConfig:
    """Runtime helper that exposes tooling configuration to the application."""

    def __init__(
        self,
        *,
        file_model: ToolingFileModel,
        project_root: Path,
    ) -> None:
        self._model = file_model
        self._project_root = project_root

    @cached_property
    def agent_model(self) -> str:
        return self._model.agent.model

    @cached_property
    def tool_approvals(self) -> Mapping[str, ToolApprovalSettings]:
        return self._model.tool_approvals

    def server_config(
        self,
        platform_slugs: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        """Return the server configuration tailored to the provided platforms."""

        config: dict[str, dict[str, Any]] = {}

        for name, server in self._model.servers.base.items():
            config[name] = server.as_client_config(
                project_root=self._project_root,
            )

        for slug in platform_slugs:
            server = self._model.servers.platforms.get(slug)
            if server is None:
                continue
            config[slug] = server.as_client_config(
                project_root=self._project_root,
            )

        return config

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        project_root: Path,
    ) -> "ToolingConfig":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        file_model = ToolingFileModel.model_validate(data)
        return cls(file_model=file_model, project_root=project_root)
