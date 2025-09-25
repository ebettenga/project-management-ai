from __future__ import annotations

import asyncio
from logging import Logger
from typing import Dict, List

from slack_bolt import Ack
from slack_sdk import WebClient

from ai.agents.mcp.memory_agent import delete_memories
from listeners.agent_interrupts.storage import (
    delete_forget_request,
    load_forget_request,
)


def _render_memory_status(fact: str, keywords: List[str], status: str) -> List[Dict[str, object]]:
    fact_text = fact or "(memory missing)"
    blocks: List[Dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Memory*\n{fact_text}",
            },
        }
    ]

    if keywords:
        keyword_text = ", ".join(keywords)
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Keywords:* {keyword_text}",
                    }
                ],
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": status,
                }
            ],
        }
    )

    return blocks


async def delete_memory_request(
    logger: Logger,
    ack: Ack,
    body: dict,
    _client: WebClient,
    respond,
):
    await ack()

    action = (body.get("actions") or [{}])[0]
    request_id = action.get("value")
    if not request_id:
        await respond(
            text="This approval is missing its data.",
            replace_original=False,
            response_type="ephemeral",
        )
        return

    request = load_forget_request(request_id)
    if not request:
        await respond(
            text="This memory approval has already been handled.",
            replace_original=True,
        )
        return

    user_id = body.get("user", {}).get("id")
    if user_id and request.get("user_id") and request["user_id"] != user_id:
        await respond(
            text="Only the original requester can respond to this approval.",
            replace_original=False,
            response_type="ephemeral",
        )
        return

    memory_id = request.get("memory_id")
    if not memory_id:
        delete_forget_request(request_id)
        await respond(
            text="This memory approval was missing its target.",
            replace_original=True,
        )
        return

    loop = asyncio.get_running_loop()

    try:
        result = await loop.run_in_executor(None, delete_memories, [memory_id])
    except Exception as error:  # pragma: no cover - Slack runtime handler
        logger.error("Failed to delete memory %s: %s", memory_id, error)
        await respond(
            text="I couldn't delete this memory. Please try again later.",
            replace_original=False,
            response_type="ephemeral",
        )
        return

    deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
    status_text = "Memory deleted." if deleted > 0 else "I could not find that memory to delete."

    await respond(
        replace_original=True,
        text=status_text,
        blocks=_render_memory_status(
            request.get("fact", ""),
            request.get("keywords", []),
            status_text,
        ),
    )

    delete_forget_request(request_id)


async def skip_memory_request(
    logger: Logger,
    ack: Ack,
    body: dict,
    _client: WebClient,
    respond,
):
    await ack()

    action = (body.get("actions") or [{}])[0]
    request_id = action.get("value")
    if not request_id:
        await respond(
            text="This approval is missing its data.",
            replace_original=False,
            response_type="ephemeral",
        )
        return

    request = load_forget_request(request_id)
    if not request:
        await respond(
            text="This memory approval has already been handled.",
            replace_original=True,
        )
        return

    user_id = body.get("user", {}).get("id")
    if user_id and request.get("user_id") and request["user_id"] != user_id:
        await respond(
            text="Only the original requester can respond to this approval.",
            replace_original=False,
            response_type="ephemeral",
        )
        return

    await respond(
        replace_original=True,
        text="Kept. The memory was not deleted.",
        blocks=_render_memory_status(
            request.get("fact", ""),
            request.get("keywords", []),
            "Kept. The memory was not deleted.",
        ),
    )

    delete_forget_request(request_id)
