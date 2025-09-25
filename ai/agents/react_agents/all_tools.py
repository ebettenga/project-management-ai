"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import json
import logging
import os
from typing import Any, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from dotenv import load_dotenv
from listeners.agent_interrupts import (
    create_approval_tool,
    create_user_question_tool,
)
from ai.agents.react_agents.tool_wrappers import tool_approve
from listeners.agent_interrupts.common import SlackContext

load_dotenv()
DB_URI = os.getenv("POSTGRES_URL")

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_CONFIG: dict[str, dict[str, Any]] = {
    "jira_create_issue": {
        "summary": "Approve creating a new Jira issue?",
        "context": "The agent will draft and submit a new Jira issue via the Jira MCP server.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "jira_update_issue": {
        "summary": "Approve updating an existing Jira issue?",
        "context": "The agent plans to modify fields on an existing Jira issue.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "jira_transition_issue": {
        "summary": "Approve moving a Jira issue to a new status?",
        "context": "The agent will trigger a workflow transition for the selected issue.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "jira_add_comment": {
        "summary": "Approve posting a Jira comment?",
        "context": "The agent will add a comment to the specified Jira issue on your behalf.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "jira_create_issue_link": {
        "summary": "Approve linking Jira issues?",
        "context": "The agent will create a relationship link between Jira issues.",
        "allow_edit": True,
        "allow_reject": True,
    },
}


def _load_approval_config() -> dict[str, dict[str, Any]]:
    raw = os.getenv("TOOL_APPROVAL_CONFIG")
    if not raw:
        return DEFAULT_APPROVAL_CONFIG

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("TOOL_APPROVAL_CONFIG env var is not valid JSON; using defaults")
        return DEFAULT_APPROVAL_CONFIG

    if not isinstance(parsed, dict):
        logger.warning("TOOL_APPROVAL_CONFIG must be a JSON object; using defaults")
        return DEFAULT_APPROVAL_CONFIG

    cleaned: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(value, dict):
            cleaned[key] = value

    return {**DEFAULT_APPROVAL_CONFIG, **cleaned}


APPROVAL_CONFIG = _load_approval_config()

AGENT_PROMPT = (
    "You are a project management assistant in a slack app. "
    "You can reach MCP tools via this environment. "
    "Never guess, always call the tool first. "
    "Store any information you recieve to memory. "
    "You primary help with located things in jira and performing actions on their behalf. "
    "keep research brief. "
    "if something doesn't make sense or you get stuck, ask the user using the ask_user tool. "
    "Call tools proactively whenever they can help and then explain the result succinctly. "
)

_SERVER_CONFIG = {
    "time": {
        "command": "python",
        "args": [
            "/Users/ethanbett/Desktop/project_management_bot/ai/agents/mcp/time_server.py"
        ],
        "transport": "stdio",
    },
    "memory": {
        "command": "python",
        "args": [
            "/Users/ethanbett/Desktop/project_management_bot/ai/agents/mcp/memory_agent.py"
        ],
        "transport": "stdio",
        "env": os.environ.copy(),
    },
    "jira": {
        "transport": "streamable_http",
        "url": "http://localhost:8000/mcp"
    },
    # "asana": {
    #   "command": "npx",
    #   "args": ["-y", "@roychri/mcp-server-asana"],
    #   "env": {
    #     "ASANA_ACCESS_TOKEN": os.environ.copy()
    #   }
    # }
}

client = MultiServerMCPClient(_SERVER_CONFIG)

async def ask_agent(
    payload: dict[str, Any] | Command,
    *,
    thread_id: str | None = None,
    slack_context: Optional[SlackContext] = None,
):
    if isinstance(payload, dict) and "messages" not in payload:
        raise ValueError("ask_agent expects a payload with a 'messages' key when using dict input.")

    config = {"configurable": {}}

    if thread_id:
        config["configurable"].update({"thread_id": thread_id})

    
    tools = list(await client.get_tools())
    wrapped_tools: list[BaseTool] = []
    removal_list = []
    for tool in tools:
        tool_name = getattr(tool, "name", "")

        approval_settings = APPROVAL_CONFIG.get(tool_name)
        if approval_settings:
            wrapped_tools.append(
                tool_approve(
                    tool,
                    summary=approval_settings.get("summary"),
                    context=approval_settings.get("context"),
                    allow_edit=approval_settings.get("allow_edit", False),
                    allow_reject=approval_settings.get("allow_reject", True),
                )
            )
            removal_list.append(tool)

            continue
        # We add tools that aren't wrapped here so we can just replace the tools wholesale
        wrapped_tools.append(tool)

    tools = wrapped_tools
    tools.append(create_approval_tool(slack_context))
    tools.append(create_user_question_tool(slack_context))

    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        await checkpointer.setup()
        agent = create_react_agent(
            "openai:gpt-4.1",
            tools,
            prompt=AGENT_PROMPT,
            checkpointer=checkpointer,
        )

        return await agent.ainvoke(payload, config=config)
