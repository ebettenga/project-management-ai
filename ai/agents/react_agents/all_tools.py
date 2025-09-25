"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import os
from typing import Any, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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

AGENT_PROMPT = (
    "You are a project management assistant in a slack app. "
    "You can reach MCP tools via this environment. "
    "Available tools:\n- time: Call this whenever the user asks about the current time or date.\n "
    "save_memory: save facts provided to long term memory \n"
    "search_memory: search memories that were stored for related info\n"
    "request_slack_approval: when an action needs a human decision or more context, gather details and pause for review.\n"
    "Never guess the time—always call the tool first. "
    "Store any information you recieve to memory"
    "Call tools proactively whenever they can help and then explain the result succinctly."
)

client = MultiServerMCPClient(
    {
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
            "env": os.environ.copy()
        },
    }
)


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

    wrapped_tools = []
    for tool in tools:
        if getattr(tool, "name", "") == "get_datetime":
            wrapped_tools.append(
                tool_approve(
                    tool,
                    summary="Allow the agent to fetch the current date and time?",
                    context="The agent is requesting to run the time helper tool to retrieve the current UTC timestamp.",
                    allow_edit=False,
                    allow_reject=True,
                )
            )
        else:
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
