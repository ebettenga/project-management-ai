import asyncio
from functools import partial
from logging import Logger
from typing import Any, Dict, List
from uuid import uuid4

from slack_bolt import Ack, BoltContext, Say
from slack_sdk import WebClient

from ai.agents.mcp.memory_agent import save_memory, search_memory
from listeners.agent_interrupts.storage import save_forget_request
from listeners.listener_utils.listener_constants import (
    FORGET_ACTION_DELETE,
    FORGET_ACTION_SKIP,
)


async def remember_callback(
    client: WebClient,
    ack: Ack,
    command: Dict[str, Any],
    say: Say,
    logger: Logger,
    context: BoltContext,
):
    try:
        await ack()
        user_id = context["user_id"]
        channel_id = context["channel_id"]
        text = (command.get("text") or "").strip()

        if not text:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="I need something to remember. Please provide a fact or note to save.",
            )
            return
        
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Let me save that for you",
        )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, save_memory, text)

        saved_count = result.get("saved", 0)
        if saved_count <= 0:
            message = result.get("message", "I couldn't find any distinct facts to save.")
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=message,
            )
            return

        facts: List[str] = result.get("facts") or []
        keywords: List[str] = result.get("keywords") or []

        facts_block = "\n".join(f"• {fact}" for fact in facts)
        keywords_text = ", ".join(keywords)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                f"Saved {saved_count} fact(s) to memory.\n\n"
                f"Facts:\n{facts_block}\n\n"
                f"Keywords: {keywords_text if keywords_text else 'None'}"
            ),
        )

    except Exception as error:  # pragma: no cover - Slack runtime handler
        logger.error("/remember command failed", exc_info=error)
        await client.chat_postEphemeral(
            channel=context.get("channel_id"),
            user=context.get("user_id"),
            text="Sorry, I ran into a problem while saving that memory.",
        )


async def ask_memory_callback(
    client: WebClient,
    ack: Ack,
    command: Dict[str, Any],
    say: Say,
    logger: Logger,
    context: BoltContext,
):
    try:
        await ack()
        user_id = context["user_id"]
        channel_id = context["channel_id"]
        query = (command.get("text") or "").strip()

        if not query:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Tell me what to look for and I'll search our memories.",
            )
            return
        
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Let me see what I can find.",
        )


        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, search_memory, query)


        if not results:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="I couldn't find anything matching that yet.",
            )
            return

        render_lines = []
        for index, item in enumerate(results, start=1):
            fact = item.get("fact", "(missing fact)")
            keywords = ", ".join(item.get("keywords") or [])
            render_lines.append(f"{index}. {fact}\n   keywords: {keywords if keywords else 'None'}")

        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Here is what I found:\n\n" + "\n\n".join(render_lines),
        )

    except Exception as error:  # pragma: no cover - Slack runtime handler
        logger.error("/ask command failed", exc_info=error)
        await client.chat_postEphemeral(
            channel=context.get("channel_id"),
            user=context.get("user_id"),
            text="Sorry, I ran into a problem while searching our memories.",
        )


def _build_forget_blocks(memory: Dict[str, Any], request_id: str) -> List[Dict[str, Any]]:
    fact = memory.get("fact") or "(missing fact)"
    keywords = memory.get("keywords") or []
    created_at = memory.get("created_at")

    blocks: List[Dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Memory*\n{fact}"},
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

    if created_at:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Recorded at: {created_at}",
                    }
                ],
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Delete"},
                    "style": "danger",
                    "action_id": FORGET_ACTION_DELETE,
                    "value": request_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep"},
                    "action_id": FORGET_ACTION_SKIP,
                    "value": request_id,
                },
            ],
        }
    )

    return blocks


async def forget_memory_callback(
    client: WebClient,
    ack: Ack,
    command: Dict[str, Any],
    say: Say,
    logger: Logger,
    context: BoltContext,
):
    try:
        await ack()
        user_id = context["user_id"]
        channel_id = context["channel_id"]
        query = (command.get("text") or "").strip()

        if not query:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Tell me which memory to forget and I'll see what's stored.",
            )
            return

        loop = asyncio.get_running_loop()
        search_fn = partial(search_memory, query, 5, 3)
        results = await loop.run_in_executor(None, search_fn)

        if not results:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="I couldn't find any memories that match that description.",
            )
            return

        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Here are the closest memories I found. Approve any you want me to forget.",
        )

        for memory in results:
            memory_id = memory.get("id")
            if not memory_id:
                continue

            request_id = uuid4().hex
            blocks = _build_forget_blocks(memory, request_id)

            response = await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Memory match: {memory.get('fact', '')[:200]}",
                blocks=blocks,
            )

            save_forget_request(
                request_id,
                {
                    "memory_id": memory_id,
                    "fact": memory.get("fact"),
                    "keywords": memory.get("keywords") or [],
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "message_ts": response.get("message_ts"),
                    "created_at": memory.get("created_at"),
                },
            )

    except Exception as error:  # pragma: no cover - Slack runtime handler
        logger.error("/forget command failed", exc_info=error)
        await client.chat_postEphemeral(
            channel=context.get("channel_id"),
            user=context.get("user_id"),
            text="Sorry, something went wrong while preparing those forget approvals.",
        )
