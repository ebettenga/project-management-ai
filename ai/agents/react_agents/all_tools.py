"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from dotenv import load_dotenv

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


@dataclass(frozen=True)
class SlackContext:
    """Slack context passed to the agent for tool calls."""

    channel_id: str
    user_id: str
    thread_ts: Optional[str]
    thread_id: Optional[str]

    def as_json(self) -> str:
        return json.dumps(
            {
                "channel_id": self.channel_id,
                "user_id": self.user_id,
                "thread_ts": self.thread_ts,
                "thread_id": self.thread_id,
            }
        )


def _build_approval_tool(slack_context: Optional[SlackContext]) -> StructuredTool:
    """Create a structured tool that interrupts execution pending Slack approval."""

    context_payload = slack_context.as_json() if slack_context else None

    def request_slack_approval(
        command: str,
        summary: str,
        additional_context: str | None = None,
    ) -> dict[str, Any]:
        """Request a human reviewer in Slack to approve a command before it runs."""

        approval_payload: Dict[str, Any] = {
            "type": "approval_request",
            "command": command,
            "summary": summary,
            "additional_context": additional_context,
        }

        if context_payload is not None:
            approval_payload["slack_context"] = context_payload

        resume_value = interrupt(approval_payload)

        # The resume value can be any JSON-serialisable object.
        return resume_value  # type: ignore[return-value]

    return StructuredTool.from_function(
        func=request_slack_approval,
        name="request_slack_approval",
        description=(
            "Pause execution and ask a human to approve or edit the provided command."
            "Always supply a concise summary of why approval is needed and what you are attempting to perform"
        ),
    )


def _build_user_question_tool(slack_context: Optional[SlackContext]) -> StructuredTool:
    """Create a structured tool that asks a Slack user for input via an interrupt."""

    context_payload = slack_context.as_json() if slack_context else None

    def ask_user(
        question: str,
        context: str | None = None,
    ) -> str:
        """Pause execution, ask the user a question, and resume with their answer."""

        question_payload: Dict[str, Any] = {
            "type": "user_question",
            "question": question,
            "context": context,
        }

        if context_payload is not None:
            question_payload["slack_context"] = context_payload

        resume_value = interrupt(question_payload)

        if isinstance(resume_value, dict):
            answer = resume_value.get("answer")
            if isinstance(answer, str):
                return answer

        if isinstance(resume_value, str):
            return resume_value

        raise ValueError(
            "ask_user tool expected an answer string in the resume payload, "
            "but received an unsupported response."
        )

    return StructuredTool.from_function(
        func=ask_user,
        name="ask_user",
        description=(
            "Pause execution and request information from the user. "
            "Provide a concise question and optional context that will be shown in Slack."
        ),
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
    tools.append(_build_approval_tool(slack_context))
    tools.append(_build_user_question_tool(slack_context))

    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        await checkpointer.setup()
        agent = create_react_agent(
            "openai:gpt-4.1",
            tools,
            prompt=AGENT_PROMPT,
            checkpointer=checkpointer,
        )

        return await agent.ainvoke(payload, config=config)
