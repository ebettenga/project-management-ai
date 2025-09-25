"""Slack-facing helpers for user-question interrupts."""

from __future__ import annotations

from logging import Logger
from typing import Any
from uuid import uuid4

from langgraph.types import Interrupt
from slack_sdk import WebClient

from listeners.agent_interrupts.common import sanitize_text
from listeners.agent_interrupts.storage import save_question_request
from listeners.listener_utils.listener_constants import QUESTION_ACTION_OPEN_MODAL


async def handle_question_interrupt(
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
    question_data = interrupt.value

    if not isinstance(question_data, dict):
        logger.error(
            "Question interrupt payload was not a dictionary: %s", question_data
        )
        return

    question = sanitize_text(question_data.get("question"), "(no question provided)")
    context = sanitize_text(question_data.get("context"), "")
    button_text = sanitize_text(question_data.get("button_text"), "Answer question")
    modal_title = sanitize_text(question_data.get("modal_title"), "Provide an answer")
    submit_label = sanitize_text(question_data.get("submit_label"), "Submit")
    placeholder = sanitize_text(
        question_data.get("placeholder"),
        "Provide any details that will help the bot.",
    )

    block_id = f"question_actions_{uuid4().hex[:8]}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Bolty needs your input*\n{question}",
            },
        },
    ]

    if context:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": context,
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
                    "text": {"type": "plain_text", "text": button_text},
                    "action_id": QUESTION_ACTION_OPEN_MODAL,
                    "value": interrupt.id,
                }
            ],
        }
    )

    response = await client.chat_postMessage(
        channel=channel_id,
        blocks=blocks,
        text=question,
    )

    conversation_ts = response["ts"]

    save_question_request(
        interrupt.id,
        {
            "thread_id": thread_id,
            "channel_id": channel_id,
            "thread_ts": conversation_ts,
            "question": question,
            "context": context,
            "prompt": prompt,
            "requester_user_id": user_id,
            "question_message_ts": response["ts"],
            "tool_call_id": interrupt.id,
            "tool_name": "ask_user",
            "modal_title": modal_title,
            "submit_label": submit_label,
            "placeholder": placeholder,
            "button_text": button_text,
        },
    )

    logger.info("Question request logged for interrupt %s", interrupt.id)
