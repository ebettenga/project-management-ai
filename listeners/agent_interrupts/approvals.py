"""Slack-facing helpers for approval interrupts."""

from __future__ import annotations

from logging import Logger
from typing import Any
from uuid import uuid4

from langgraph.types import Interrupt
from slack_sdk import WebClient

from listeners.agent_interrupts.common import sanitize_text
from listeners.agent_interrupts.storage import save_approval_request
from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
)


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

    summary = sanitize_text(approval_data.get("summary"), "Approval requested")
    command_text = approve_payload_text(approval_data.get("command"))
    additional_context = sanitize_optional(approval_data.get("additional_context"))

    block_id = f"approval_actions_{uuid4().hex[:8]}"

    blocks: list[dict[str, Any]] = [
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

    save_approval_request(
        interrupt.id,
        {
            "thread_id": thread_id,
            "channel_id": channel_id,
            "thread_ts": conversation_ts,
            "command": command_text,
            "summary": summary,
            "additional_context": additional_context or None,
            "prompt": prompt,
            "approval_message_ts": response["ts"],
            "requester_user_id": user_id,
            "tool_call_id": interrupt.id,
            "tool_name": "request_slack_approval",
        },
    )
    logger.info("Approval request logged for interrupt %s", interrupt.id)


def approve_payload_text(value: str | None) -> str:
    return sanitize_text(value, "(no command provided)")


def sanitize_optional(value: str | None) -> str:
    return sanitize_text(value, "")
