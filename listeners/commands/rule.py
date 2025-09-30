from logging import Logger

from slack_bolt import Ack, BoltContext, Say
from slack_sdk import WebClient

from db.models import User
from db.session import get_session


async def rule_callback(
    client: WebClient,
    ack: Ack,
    command,
    context: BoltContext,
    say: Say,
    logger: Logger,
):
    """Store a user-specific rule that will be injected into future LLM prompts."""

    await ack()

    user_id = context.get("user_id")
    channel_id = context.get("channel_id")
    rule_text = (command.get("text") or "").strip()

    if not user_id or not channel_id:
        logger.error("Missing channel or user context for /rule command: %s", command)
        return

    if not rule_text:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Please provide the rule text, for example `/rule Always include Jira ticket links`.",
        )
        return

    try:
        with get_session() as session:
            user = User.create_if_not_exists(session, slack_user_id=user_id)

            existing_prefs = dict(user.model_preferences or {})
            rules_value = existing_prefs.get("rules")

            if isinstance(rules_value, list):
                rules: list[str] = [str(item) for item in rules_value if str(item).strip()]
            else:
                rules = []

            if rule_text in rules:
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="You already saved that rule.",
                )
                return

            rules.append(rule_text)
            existing_prefs["rules"] = rules
            user.model_preferences = existing_prefs

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to persist rule for user %s", user_id)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Sorry, I couldn't save that rule. Please try again shortly.",
        )
        return

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"Saved your rule: {rule_text}",
    )
