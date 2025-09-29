from logging import Logger

from slack_bolt import Ack, BoltContext, Say
from slack_sdk import WebClient

from ai.agents.react_agents.all_tools import ask_agent
from ai.agents.react_agents.thread_state import get_or_create_thread_id
from listeners.agent_interrupts.common import SlackContext
from listeners.user_preferences import (
    build_rules_system_message,
    build_user_metadata_message,
    get_user_rules,
)
from listeners.agent_interrupts import (
    build_agent_response_blocks,
    extract_last_ai_text,
    handle_agent_interrupt,
)

"""
Callback for handling the 'ask-llm' command. It acknowledges the command, retrieves the user's ID and prompt,
checks if the prompt is empty, and responds with either an error message or the provider's response.
"""


async def llm_callback(
    client: WebClient, ack: Ack, command, say: Say, logger: Logger, context: BoltContext
):
    try:
        await ack()
        user_id = context["user_id"]
        channel_id = context["channel_id"]
        thread_ts = command.get("thread_ts") or context.get("thread_ts")

        thread_id = get_or_create_thread_id(
            channel_id=channel_id, user_id=user_id, thread_ts=thread_ts
        )
        prompt = command["text"]

        if prompt == "":
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Looks like you didn't provide a prompt. Try again.",
            )
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Working on that for you. give me a second plz.",
            )
            rules = get_user_rules(user_id)
            messages = []
            metadata_message = build_user_metadata_message(user_id)
            if metadata_message:
                messages.append(metadata_message)
            rules_message = build_rules_system_message(rules)
            if rules_message:
                messages.append(rules_message)
            messages.append({"role": "user", "content": prompt})

            agent_payload = {"messages": messages}
            slack_context = SlackContext(
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=thread_ts,
                thread_id=thread_id,
            )
            response = await ask_agent(
                agent_payload, thread_id=thread_id, slack_context=slack_context
            )

            if "__interrupt__" in response:
                for interrupt in response["__interrupt__"]:
                    await handle_agent_interrupt(
                        client=client,
                        interrupt=interrupt,
                        channel_id=channel_id,
                        user_id=user_id,
                        thread_ts=thread_ts,
                        thread_id=thread_id,
                        prompt=prompt,
                        logger=logger,
                    )
                return
            else:
                text = extract_last_ai_text(response["messages"])
                if not text:
                    text = "(agent did not return text)"
                await client.chat_postMessage(
                    channel=channel_id,
                    user=user_id,
                    blocks=build_agent_response_blocks(prompt, text),
                )
    except Exception as e:
        logger.error(e)
        await client.chat_postEphemeral(
            channel=channel_id, user=user_id, text=f"Received an error from Bolty: {e}"
        )
