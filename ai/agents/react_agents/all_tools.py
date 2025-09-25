"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import json
import logging
import os
from typing import Any, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.tools import BaseTool
from langgraph.errors import GraphInterrupt
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

AGENT_PROMPT = (
    "You are a project management assistant in a slack app. "
    "You can reach MCP tools via this environment. "
    "Never guess, always call the tool first. "
    "Store any information you recieve to memory. "
    "You primary help with located things in jira and performing actions on their behalf. "
    "keep research brief. Create the summary, name, and/or description yourself if details are not provided. default tickets to normal prioity unless otherwise asked. "
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
    }
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

    try:
        tools = list(await client.get_tools())
    except Exception as error:
        logger.warning(
            "Failed to load tools from MCP servers; continuing with built-ins only: %s",
            error,
            exc_info=True,
        )
        tools = []
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

        try:
            return await agent.ainvoke(payload, config=config)
        except GraphInterrupt as interrupt:
            interrupts = list(getattr(interrupt, "interrupts", [])) or [interrupt]
            return {"__interrupt__": interrupts}
