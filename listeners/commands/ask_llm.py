from slack_bolt import Ack, Say, BoltContext
from logging import Logger
from slack_sdk import WebClient
from ai.agents.react_agents.examples_agent import ask_agent

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

        # Ai Thread ID for persistence
        thread_id = (
            f"{user_id}-{channel_id}-{thread_ts}" if thread_ts else f"{user_id}-{channel_id}"
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
            agent_payload = {"messages": [{"role": "user", "content": prompt}]}
            agent_kwargs = {"thread_id": thread_id}
            response = await ask_agent(agent_payload, **agent_kwargs)
            text = response["messages"][-1].content
            await client.chat_postMessage(
                channel=channel_id,
                user=user_id,
                blocks=[
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
                                        "text": text,
                                    }
                                ],
                            },
                        ],
                    }
                ],
            )
    except Exception as e:
        logger.error(e)
        await client.chat_postEphemeral(
            channel=channel_id, user=user_id, text=f"Received an error from Bolty: {e}"
        )