from __future__ import annotations

from logging import Logger
from typing import Any
from uuid import uuid4

from langgraph.errors import GraphInterrupt
from slack_sdk import WebClient

from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
)
from state_store.approval_requests import save_request


def build_agent_response_blocks(prompt: str, response_text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_quote",
                    "elements": [{"type": "text", "text": prompt}],
                },
                {
                    "type": "rich_text_section",
                    "elements": [
                        {
                            "type": "text",
                            "text": response_text,
                        }
                    ],
                },
            ],
        }
    ]


async def handle_approval_interrupt(
    *,
    client: WebClient,
    interrupt: GraphInterrupt,
    channel_id: str,
    user_id: str,
    thread_ts: str | None,
    thread_id: str,
    prompt: str,
    logger: Logger,
) -> None:
    if not interrupt.args:
        logger.error("Received GraphInterrupt without interrupt payloads")
        return

    for interrupt_payload in interrupt.args[0]:
        approval_data = interrupt_payload.value

        if not isinstance(approval_data, dict):
            logger.error("Approval interrupt payload was not a dictionary: %s", approval_data)
            continue

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
                        "value": interrupt_payload.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": APPROVAL_ACTION_EDIT,
                        "value": interrupt_payload.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": APPROVAL_ACTION_REJECT,
                        "value": interrupt_payload.id,
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
            interrupt_payload.id,
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
            },
        )
        logger.info("Approval request logged for interrupt %s", interrupt_payload.id)
