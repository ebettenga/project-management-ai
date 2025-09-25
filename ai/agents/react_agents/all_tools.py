"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import os
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from dotenv import load_dotenv

load_dotenv()
DB_URI = os.getenv("POSTGRES_URL")

AGENT_PROMPT = (
    "You are a project management assistant in a slack app. "
    "You can reach MCP tools via this environment. "
    "Available tools:\n- time: Call this whenever the user asks about the current time or date.\n "
    "save_memory: save facts provided to long term memory \n"
    "search_memory: search memories that were stored for related info"
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


async def ask_agent(payload: dict[str, Any], thread_id=None):
    if "messages" not in payload:
        raise ValueError("ask_agent expects a payload with a 'messages' key.")

    config = {
        "configurable": {
        }
    }

    tools = await client.get_tools()
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        await checkpointer.setup()
        agent = create_react_agent(
            "openai:gpt-4.1",
            tools,
            prompt=AGENT_PROMPT,
            checkpointer=checkpointer
        )

        if thread_id:
            config["configurable"].update({"thread_id": thread_id})

        return await agent.ainvoke(payload, config=config)

