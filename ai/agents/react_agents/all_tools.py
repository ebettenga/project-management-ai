"""LangGraph agent wired to MCP tools used by the Slack ask command."""

import copy
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
from ai.agents.react_agents.thread_state import create_clear_thread_tool
from listeners.agent_interrupts.common import SlackContext
from listeners.user_management_platforms import get_user_management_platforms

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
    "asana_create_task": {
        "summary": "Approve creatong an Asana task?",
        "context": "The agent will modify fields on an existing Asana task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "asana_update_task": {
        "summary": "Approve updating an Asana task?",
        "context": "The agent will modify fields on an existing Asana task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "asana_add_task_dependencies": {
        "summary": "Approve editing Asana task dependencies?",
        "context": "The agent will change dependency relationships for the specified task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "asana_add_task_dependents": {
        "summary": "Approve editing Asana task dependents?",
        "context": "The agent will update which tasks depend on the specified task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "asana_set_parent_for_task": {
        "summary": "Approve reorganizing Asana task hierarchy?",
        "context": "The agent will change the parent or position of the specified task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "asana_delete_project_status": {
        "summary": "Approve deleting an Asana project status update?",
        "context": "The agent will permanently remove the selected project status update.",
        "allow_edit": False,
        "allow_reject": True,
    },
    "create_event": {
        "summary": "Approve creating a Google Calendar event?",
        "context": "The agent will add a new event to your Google Calendar via the Google MCP server.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "modify_event": {
        "summary": "Approve updating a Google Calendar event?",
        "context": "The agent will change details on an existing Google Calendar event.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "delete_event": {
        "summary": "Approve deleting a Google Calendar event?",
        "context": "The agent will remove the specified event from Google Calendar.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_drive_file": {
        "summary": "Approve creating a Google Drive file?",
        "context": "The agent will create or upload a file in Google Drive.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "send_gmail_message": {
        "summary": "Approve sending a Gmail message?",
        "context": "The agent will send an email through your Gmail account.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "draft_gmail_message": {
        "summary": "Approve drafting a Gmail message?",
        "context": "The agent will create a draft email in your Gmail account.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "manage_gmail_label": {
        "summary": "Approve managing Gmail labels?",
        "context": "The agent will create, update, or delete labels in Gmail.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "modify_gmail_message_labels": {
        "summary": "Approve updating Gmail message labels?",
        "context": "The agent will change label assignments on existing Gmail messages.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "batch_modify_gmail_message_labels": {
        "summary": "Approve bulk Gmail label changes?",
        "context": "The agent will modify labels across multiple Gmail messages in one operation.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_doc": {
        "summary": "Approve creating a Google Doc?",
        "context": "The agent will create a new Google Document in your Drive.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "modify_doc_text": {
        "summary": "Approve editing Google Doc text?",
        "context": "The agent will modify the text content of a Google Document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "find_and_replace_doc": {
        "summary": "Approve running find and replace in a Google Doc?",
        "context": "The agent will search for text and replace it within a Google Document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "insert_doc_elements": {
        "summary": "Approve inserting structured elements into a Google Doc?",
        "context": "The agent will insert tables, lists, or other structural elements into the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "insert_doc_image": {
        "summary": "Approve adding an image to a Google Doc?",
        "context": "The agent will insert an image into the specified Google Document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "update_doc_headers_footers": {
        "summary": "Approve updating Google Doc headers or footers?",
        "context": "The agent will modify header or footer content in the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "batch_update_doc": {
        "summary": "Approve running batch updates on a Google Doc?",
        "context": "The agent will execute multiple structural changes on the document in a single request.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_table_with_data": {
        "summary": "Approve creating a data table in a Google Doc?",
        "context": "The agent will build and populate a table within the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_document_comment": {
        "summary": "Approve adding a Google Doc comment?",
        "context": "The agent will leave a new comment in the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "reply_to_document_comment": {
        "summary": "Approve replying to a Google Doc comment?",
        "context": "The agent will post a reply to an existing comment in the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "resolve_document_comment": {
        "summary": "Approve resolving a Google Doc comment?",
        "context": "The agent will mark a comment thread as resolved in the document.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_form": {
        "summary": "Approve creating a Google Form?",
        "context": "The agent will generate a new Google Form in your account.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "set_publish_settings": {
        "summary": "Approve updating Google Form publish settings?",
        "context": "The agent will change how the selected form is published or shared.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_presentation": {
        "summary": "Approve creating a Google Slides presentation?",
        "context": "The agent will create a new Google Slides deck in your Drive.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "batch_update_presentation": {
        "summary": "Approve bulk updates to a Google Slides presentation?",
        "context": "The agent will apply structural changes to the presentation via the Slides API.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_presentation_comment": {
        "summary": "Approve adding a Google Slides comment?",
        "context": "The agent will add a new comment on the specified presentation slide.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "reply_to_presentation_comment": {
        "summary": "Approve replying to a Google Slides comment?",
        "context": "The agent will respond to an existing comment thread in the presentation.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "resolve_presentation_comment": {
        "summary": "Approve resolving a Google Slides comment?",
        "context": "The agent will mark a presentation comment thread as resolved.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "modify_sheet_values": {
        "summary": "Approve modifying values in a Google Sheet?",
        "context": "The agent will write, update, or clear data within the specified spreadsheet range.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_spreadsheet": {
        "summary": "Approve creating a Google Spreadsheet?",
        "context": "The agent will create a new Google Sheet in your Drive.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_sheet": {
        "summary": "Approve adding a sheet to a Google Spreadsheet?",
        "context": "The agent will insert a new tab within an existing spreadsheet.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_spreadsheet_comment": {
        "summary": "Approve adding a Google Sheet comment?",
        "context": "The agent will leave a comment on the specified spreadsheet cell range.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "reply_to_spreadsheet_comment": {
        "summary": "Approve replying to a Google Sheet comment?",
        "context": "The agent will post a reply within a spreadsheet comment thread.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "resolve_spreadsheet_comment": {
        "summary": "Approve resolving a Google Sheet comment?",
        "context": "The agent will mark a spreadsheet comment thread as resolved.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "send_message": {
        "summary": "Approve sending a Google Chat message?",
        "context": "The agent will post a message into the specified Google Chat space.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_task_list": {
        "summary": "Approve creating a Google Tasks list?",
        "context": "The agent will create a new task list in Google Tasks.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "update_task_list": {
        "summary": "Approve renaming or updating a Google Tasks list?",
        "context": "The agent will modify the metadata of the specified task list.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "delete_task_list": {
        "summary": "Approve deleting a Google Tasks list?",
        "context": "The agent will remove the specified task list and its tasks from Google Tasks.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "create_task": {
        "summary": "Approve creating a Google Task?",
        "context": "The agent will add a new task to the specified task list.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "update_task": {
        "summary": "Approve updating a Google Task?",
        "context": "The agent will modify fields on the selected task.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "delete_task": {
        "summary": "Approve deleting a Google Task?",
        "context": "The agent will remove the specified task from Google Tasks.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "move_task": {
        "summary": "Approve moving a Google Task?",
        "context": "The agent will reposition the task within its list or move it to another list.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "clear_completed_tasks": {
        "summary": "Approve clearing completed Google Tasks?",
        "context": "The agent will delete all completed tasks in the specified list.",
        "allow_edit": True,
        "allow_reject": True,
    },
    "clear_langgraph_thread": {
        "summary": "Approve clearing the agent conversation history?",
        "context": "This will remove stored LangGraph checkpoints for this Slack conversation so future interactions start fresh.",
        "allow_edit": False,
        "allow_reject": True,
    },
    "export_doc_to_pdf": {
        "summary": "Approve exporting a Google Doc to PDF?",
        "context": "The agent will generate a PDF from the document and upload it to Google Drive.",
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
    "You primary help with located things in the users preferred task management service and performing actions on their behalf. "
    "keep research brief. "
    "if something doesn't make sense or you get stuck, ask the user before precending. "
    "Call tools proactively whenever they can help and then explain the result succinctly. "
)

_BASE_SERVER_CONFIG: dict[str, dict[str, Any]] = {
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
    "google": {"transport": "streamable_http", "url": "http://localhost:8000/mcp"},
}

_MANAGEMENT_PLATFORM_SERVER_CONFIG: dict[str, dict[str, Any]] = {
    "jira": {"transport": "streamable_http", "url": "http://localhost:8010/mcp"},
    "asana": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@roychri/mcp-server-asana"],
        "env": os.environ.copy(),
    },
}


def _build_server_config(slack_context: Optional[SlackContext]) -> dict[str, dict[str, Any]]:
    """Return a server configuration tailored to the requesting user's platforms."""

    config = copy.deepcopy(_BASE_SERVER_CONFIG)

    slack_user_id = slack_context.user_id if slack_context else None
    selections = get_user_management_platforms(slack_user_id)
    seen_slugs: set[str] = set()
    for selection in selections:
        slug = selection.slug.lower()
        if slug in seen_slugs:
            continue
        server_entry = _MANAGEMENT_PLATFORM_SERVER_CONFIG.get(slug)
        if not server_entry:
            continue
        config[slug] = copy.deepcopy(server_entry)
        seen_slugs.add(slug)

    return config


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

    config = {"configurable": {}}

    if thread_id:
        config["configurable"].update({"thread_id": thread_id})

    server_config = _build_server_config(slack_context)
    client = MultiServerMCPClient(server_config)

    try:
        tools = list(await client.get_tools())
        wrapped_tools: list[BaseTool] = []
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
                continue
            # We add tools that aren't wrapped here so we can just replace the tools wholesale
            wrapped_tools.append(tool)

        tools = wrapped_tools
        tools.append(create_clear_thread_tool(slack_context))
        tools.append(create_approval_tool(slack_context))
        # tools.append(create_user_question_tool(slack_context))

        async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
            await checkpointer.setup()
            agent = create_react_agent(
                "openai:gpt-4.1",
                tools,
                prompt=AGENT_PROMPT,
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
