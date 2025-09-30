"""LangGraph agent wired to MCP tools used by the Slack ask command."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command

from ai.agents.react_agents.thread_state import create_clear_thread_tool
from ai.agents.react_agents.tool_wrappers import tool_approve
from ai.prompts import get_agent_prompt
from config import get_settings
from listeners.agent_interrupts import create_approval_tool
from listeners.agent_interrupts.common import SlackContext
from listeners.user_management_platforms import get_user_management_platforms

logger = logging.getLogger(__name__)

settings = get_settings()

_langfuse_handler: Optional[Any] = None
_langfuse_handler_init_failed = False


def _get_langfuse_handler() -> Optional[Any]:
    """Return a shared Langfuse callback handler if the SDK is available."""

    global _langfuse_handler, _langfuse_handler_init_failed

    if _langfuse_handler is not None or _langfuse_handler_init_failed:
        return _langfuse_handler

    if LangfuseCallbackHandler is None:
        _langfuse_handler_init_failed = True
        logger.debug(
            "Langfuse callback handler unavailable; tracing disabled for this run."
        )
        return None

    try:
        _langfuse_handler = LangfuseCallbackHandler()
    except Exception as exc:  # pragma: no cover - defensive logging
        _langfuse_handler_init_failed = True
        logger.warning(
            "Failed to initialise Langfuse callback handler; tracing disabled.",
            exc_info=exc,
        )
        return None

    return _langfuse_handler


def _selected_platform_slugs(slack_context: Optional[SlackContext]) -> set[str]:
    """Return management platform slugs enabled for the requesting Slack user."""

    slack_user_id = slack_context.user_id if slack_context else None
    selections = get_user_management_platforms(slack_user_id)
    return {
        selection.slug.lower()
        for selection in selections
        if getattr(selection, "slug", None)
    }


def _build_server_config(slack_context: Optional[SlackContext]) -> dict[str, dict[str, Any]]:
    """Return the MCP server configuration for the provided Slack context."""

    platform_slugs = _selected_platform_slugs(slack_context)
    return settings.tooling.server_config(platform_slugs)


async def ask_agent(
    payload: dict[str, Any] | Command,
    *,
    thread_id: str | None = None,
    slack_context: Optional[SlackContext] = None,
):
    if isinstance(payload, dict) and "messages" not in payload:
        raise ValueError(
            "ask_agent expects a payload with a 'messages' key when using dict input."
        )

    config: dict[str, Any] = {"configurable": {}}

    if thread_id:
        config["configurable"].update({"thread_id": thread_id})

    handler = _get_langfuse_handler()
    if handler:
        config["callbacks"] = [handler]

    metadata: dict[str, Any] = {}
    session_identifier = thread_id or (
        slack_context.thread_id if slack_context else None
    )
    if session_identifier:
        metadata["langfuse_session_id"] = session_identifier

    if slack_context:
        metadata["langfuse_user_id"] = slack_context.user_id
        metadata["slack_channel_id"] = slack_context.channel_id
        if slack_context.thread_ts:
            metadata["slack_thread_ts"] = slack_context.thread_ts

    if metadata:
        config["metadata"] = metadata

    server_config = _build_server_config(slack_context)
    client = MultiServerMCPClient(server_config)

    try:
        tools = list(await client.get_tools())
        wrapped_tools: list[BaseTool] = []
        approval_mapping = settings.tooling.tool_approvals

        for tool in tools:
            tool_name = getattr(tool, "name", "")
            approval_settings = approval_mapping.get(tool_name)
            if approval_settings:
                wrapped_tools.append(
                    tool_approve(
                        tool,
                        summary=approval_settings.summary,
                        context=approval_settings.context,
                        allow_edit=approval_settings.allow_edit,
                        allow_reject=approval_settings.allow_reject,
                    )
                )
                continue
            wrapped_tools.append(tool)

        wrapped_tools.append(create_clear_thread_tool(slack_context))
        wrapped_tools.append(create_approval_tool(slack_context))
        # wrapped_tools.append(create_user_question_tool(slack_context))

        db_uri = settings.postgres_url
        if not db_uri:
            raise RuntimeError("POSTGRES_URL is not configured")

        async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer:
            await checkpointer.setup()
            agent_prompt = get_agent_prompt()
            agent = create_react_agent(
                settings.tooling.agent_model,
                wrapped_tools,
                prompt=agent_prompt,
                checkpointer=checkpointer,
            )

            return await agent.ainvoke(payload, config=config)
    finally:
        close_async = getattr(client, "aclose", None)
        if callable(close_async):
            await close_async()
        else:
            close_sync = getattr(client, "close", None)
            if callable(close_sync):
                close_sync()

