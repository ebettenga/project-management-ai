from slack_bolt import Ack, Say, BoltContext
from logging import Logger
from slack_sdk import WebClient
from ai.agents.react_agents.examples_agent import ask_agent

"""
Callback for handling the 'ask-bolty' command. It acknowledges the command, retrieves the user's ID and prompt,
checks if the prompt is empty, and responds with either an error message or the provider's response.
"""


async def ask_callback(
    client: WebClient, ack: Ack, command, say: Say, logger: Logger, context: BoltContext
):
    try:
        await ack()
        user_id = context["user_id"]
        channel_id = context["channel_id"]
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
            response = await ask_agent({"messages": [{"role": "user", "content": prompt}]})
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
            channel=channel_id, user=user_id, text=f"Received an error from Bolty:\n{e}"
        )
