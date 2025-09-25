from __future__ import annotations

import json
from logging import Logger
from typing import Optional

from slack_bolt import Ack
from slack_sdk import WebClient

from ai.agents.react_agents.all_tools import SlackContext, ask_agent
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from listeners.listener_utils.approvals import (
    build_agent_response_blocks,
    extract_last_ai_text,
)
from listeners.listener_utils.interrupts import handle_agent_interrupt
from listeners.listener_utils.listener_constants import (
    QUESTION_MODAL_CALLBACK,
    QUESTION_MODAL_INPUT_ACTION,
    QUESTION_MODAL_INPUT_BLOCK,
)
from state_store.question_requests import delete_request, load_request


async def open_question_modal(logger: Logger, ack: Ack, body: dict, client: WebClient):
    await ack()

    try:
        interrupt_id = body["actions"][0]["value"]
        request = load_request(interrupt_id)
        if not request:
            await _notify_missing_request(client, body)
            return

        placeholder_text = request.get(
            "placeholder", "Provide any details that will help the bot."
        )

        modal_view = {
            "type": "modal",
            "callback_id": QUESTION_MODAL_CALLBACK,
            "private_metadata": json.dumps({"interrupt_id": interrupt_id}),
            "title": {"type": "plain_text", "text": request.get("modal_title", "Provide an answer")},
            "submit": {"type": "plain_text", "text": request.get("submit_label", "Submit")},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Question*\n{request['question']}",
                    },
                },
                {
                    "type": "input",
                    "block_id": QUESTION_MODAL_INPUT_BLOCK,
                    "label": {"type": "plain_text", "text": "Your answer"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": QUESTION_MODAL_INPUT_ACTION,
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": placeholder_text,
                        },
                    },
                },
            ],
        }

        context = request.get("context")
        if context:
            modal_view["blocks"].insert(
                1,
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": context},
                },
            )

        await client.views_open(trigger_id=body["trigger_id"], view=modal_view)

    except Exception as error:  # pragma: no cover - defensive guard
        logger.error("Failed to open question modal: %s", error)


async def submit_question_modal(logger: Logger, ack: Ack, body: dict, client: WebClient):
    try:
        metadata = json.loads(body["view"]["private_metadata"])
        interrupt_id = metadata.get("interrupt_id")
        if not interrupt_id:
            raise ValueError("Missing interrupt id in modal metadata")

        answer = (
            body["view"]["state"]["values"].get(QUESTION_MODAL_INPUT_BLOCK, {})
            .get(QUESTION_MODAL_INPUT_ACTION, {})
            .get("value", "")
        )

        if not answer.strip():
            await ack(
                {
                    "response_action": "errors",
                    "errors": {
                        QUESTION_MODAL_INPUT_BLOCK: "Please provide an answer before submitting.",
                    },
                }
            )
            return

        answer = answer.strip()
    except Exception as error:
        await ack()
        logger.error("Invalid modal submission: %s", error)
        return

    await ack()

    request = load_request(interrupt_id)
    if not request:
        logger.error("Question request %s could not be found", interrupt_id)
        return

    responding_user_id = body.get("user", {}).get("id")

    await _update_question_message(
        client=client,
        request=request,
        answer=answer,
        responding_user_id=responding_user_id,
    )

    slack_context = SlackContext(
        channel_id=request["channel_id"],
        user_id=request["requester_user_id"],
        thread_ts=request["thread_ts"],
        thread_id=request["thread_id"],
    )

    resume_value: dict[str, Optional[str]] = {
        "status": "answered",
        "answer": answer,
        "question": request.get("question"),
        "thread_id": request.get("thread_id"),
    }
    if responding_user_id:
        resume_value["responding_user_id"] = responding_user_id

    try:
        response = await ask_agent(
            Command(resume=resume_value),
            thread_id=request["thread_id"],
            slack_context=slack_context,
        )
    except GraphInterrupt as interrupt:
        await handle_agent_interrupt(
            client=client,
            interrupt=interrupt,
            channel_id=request["channel_id"],
            user_id=request["requester_user_id"],
            thread_ts=request["thread_ts"],
            thread_id=request["thread_id"],
            prompt=request.get("prompt", request.get("question", "")),
            logger=logger,
        )
        delete_request(interrupt_id)
        return

    text = extract_last_ai_text(response["messages"])
    if not text:
        text = "(agent did not return text)"

    await client.chat_postMessage(
        channel=request["channel_id"],
        thread_ts=request["thread_ts"],
        blocks=build_agent_response_blocks(
            request.get("prompt", request.get("question", "")),
            text,
        ),
    )

    delete_request(interrupt_id)


async def _update_question_message(
    *,
    client: WebClient,
    request: dict,
    answer: str,
    responding_user_id: Optional[str],
) -> None:
    channel_id = request["channel_id"]
    message_ts = request["question_message_ts"]

    answer_header = "Answer"
    if responding_user_id:
        answer_header = f"Answer from <@{responding_user_id}>"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Question*\n{request['question']}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{answer_header}*\n{answer}",
            },
        },
    ]

    context = request.get("context")
    if context:
        blocks.insert(
            1,
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": context},
            },
        )

    await client.chat_update(channel=channel_id, ts=message_ts, blocks=blocks)


async def _notify_missing_request(client: WebClient, body: dict) -> None:
    channel_id = body.get("channel", {}).get("id")
    user_id = body.get("user", {}).get("id")
    if channel_id and user_id:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="This request has already been handled or could not be found.",
        )
