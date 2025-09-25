from __future__ import annotations

from logging import Logger
from typing import Any, Iterable
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.messages.base import BaseMessage
from langgraph.types import Interrupt
from slack_sdk import WebClient

from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
)
from state_store.approval_requests import save_request


def _sanitize_text(value: str | None, fallback: str) -> str:
    trimmed = (value or "").strip()
    return trimmed if trimmed else fallback


def build_agent_response_blocks(prompt: str, response_text: str) -> list[dict[str, Any]]:
    safe_prompt = _sanitize_text(prompt, "(no prompt provided)")
    safe_response = _sanitize_text(response_text, "(no response returned)")

    return [
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_quote",
                    "elements": [{"type": "text", "text": safe_prompt}],
                },
                {
                    "type": "rich_text_section",
                    "elements": [
                        {
                            "type": "text",
                            "text": safe_response,
                        }
                    ],
                },
            ],
        }
    ]


def extract_last_ai_text(messages: Iterable[BaseMessage]) -> str:
    """Return the newest non-empty AI message text from the conversation."""

    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            content = message.content

            if isinstance(content, str):
                text = content.strip()
                if text:
                    return text
            elif isinstance(content, list):
                text_chunks: list[str] = []
                for chunk in content:
                    if isinstance(chunk, str):
                        text_chunks.append(chunk)
                    elif isinstance(chunk, dict) and chunk.get("type") == "text":
                        text_chunks.append(chunk.get("text", ""))

                text = "\n".join(part for part in text_chunks if part.strip())
                if text.strip():
                    return text

    return ""


async def handle_approval_interrupt(
    *,
    client: WebClient,
    interrupt: Interrupt,
    channel_id: str,
    user_id: str,
    thread_ts: str | None,
    thread_id: str,
    prompt: str,
    logger: Logger,
) -> None:
    approval_data = interrupt.value

    if not isinstance(approval_data, dict):
        logger.error("Approval interrupt payload was not a dictionary: %s", approval_data)
        return

    summary = approval_data.get("summary", "Approval requested")
    command_text = approval_data.get("command", "")
    additional_context = approval_data.get("additional_context")

    block_id = f"approval_actions_{uuid4().hex[:8]}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Approval needed*\n{summary}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Command*\n```{command_text}```",
            },
        },
    ]

    if additional_context:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Context*\n{additional_context}",
                },
            }
        )

    blocks.append(
        {
            "type": "actions",
            "block_id": block_id,
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": APPROVAL_ACTION_APPROVE,
                    "value": interrupt.id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": APPROVAL_ACTION_EDIT,
                    "value": interrupt.id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": APPROVAL_ACTION_REJECT,
                    "value": interrupt.id,
                },
            ],
        }
    )

    post_kwargs: dict[str, Any] = {
        "channel": channel_id,
        "blocks": blocks,
    }
    if thread_ts:
        post_kwargs["thread_ts"] = thread_ts

    response = await client.chat_postMessage(**post_kwargs)

    conversation_ts = thread_ts or response["ts"]

    save_request(
        interrupt.id,
        {
            "thread_id": thread_id,
            "channel_id": channel_id,
            "thread_ts": conversation_ts,
            "command": command_text,
            "summary": summary,
            "additional_context": additional_context,
            "prompt": prompt,
            "approval_message_ts": response["ts"],
            "requester_user_id": user_id,
            "tool_call_id": interrupt.id,
            "tool_name": "request_slack_approval",
        },
    )
    logger.info("Approval request logged for interrupt %s", interrupt.id)
