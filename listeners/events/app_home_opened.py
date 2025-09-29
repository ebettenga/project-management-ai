from logging import Logger
from ai.providers import get_available_providers
from slack_sdk import WebClient
from sqlalchemy import select

from db.models import User
from db.session import get_session
from listeners.user_preferences import extract_rules_from_preferences
from state_store.get_user_state import get_user_state
from listeners.user_management_platforms import (
    get_user_management_platforms,
    list_management_platforms,
)
from listeners.listener_utils.listener_constants import RULE_ACTION_DELETE

"""
Callback for handling the 'app_home_opened' event. It checks if the event is for the 'home' tab,
generates a list of model options for a dropdown menu, retrieves the user's state to set the initial option,
and publishes a view to the user's home tab in Slack.
"""


async def app_home_opened_callback(event: dict, logger: Logger, client: WebClient):
    if event.get("tab") != "home":
        return

    user_id = event.get("user")
    if not user_id:
        logger.error("app_home_opened event missing user field: %s", event)
        return

    try:
        view = build_app_home_view(user_id)
        await client.views_publish(user_id=user_id, view=view)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to publish app home: %s", exc)


def build_app_home_view(user_id: str) -> dict:
    """Return the rendered view for the Slack App Home."""

    first_name = ""
    last_name = ""
    rules: list[str] = []
    with get_session() as session:
        user_record = (
            session.execute(select(User).where(User.slack_user_id == user_id))
            .scalar_one_or_none()
        )
        if user_record is None:
            user_record = User.create_if_not_exists(session, slack_user_id=user_id)

        first_name = (user_record.first_name or "").strip()
        last_name = (user_record.last_name or "").strip()
        rules = extract_rules_from_preferences(user_record.model_preferences)

    # create a list of options for the dropdown menu each containing the model name and provider
    options = [
        {
            "text": {
                "type": "plain_text",
                "text": f"{model_info['name']} ({model_info['provider']})",
                "emoji": True,
            },
            "value": f"{model_name} {model_info['provider'].lower()}",
        }
        for model_name, model_info in get_available_providers().items()
    ]

    # retrieve user's state to determine if they already have a selected model
    user_state = get_user_state(user_id, True)
    initial_option = None
    fallback_option = None

    if user_state:
        initial_model = user_state[1]
        # set the initial option to the user's previously selected model
        initial_option = list(
            filter(lambda x: x["value"].startswith(initial_model), options)
        )
    else:
        # add an empty option if the user has no previously selected model.
        fallback_option = {
            "text": {
                "type": "plain_text",
                "text": "Select a provider",
                "emoji": True,
            },
            "value": "null",
        }
        options.append(fallback_option)

    provider_select = {
        "type": "static_select",
        "options": options,
        "action_id": "pick_a_provider",
    }
    if initial_option:
        provider_select["initial_option"] = initial_option[0]
    elif fallback_option:
        provider_select["initial_option"] = fallback_option

    # Build management platform checkbox options
    platform_records = list_management_platforms()
    platform_options = [
        {
            "text": {"type": "plain_text", "text": platform.display_name, "emoji": True},
            "value": platform.slug,
        }
        for platform in platform_records
    ]

    selected_platform_slugs = {
        selection.slug.lower() for selection in get_user_management_platforms(user_id)
    }

    initial_platform_options = [
        option
        for option in platform_options
        if option["value"].lower() in selected_platform_slugs
    ]

    platform_selection_element = None
    if platform_options:
        platform_selection_element = {
            "type": "checkboxes",
            "options": platform_options,
            "action_id": "toggle_management_platforms",
        }
        if initial_platform_options:
            platform_selection_element["initial_options"] = initial_platform_options

    first_name_input = {
        "type": "input",
        "block_id": "profile_first_name",
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "First name", "emoji": True},
        "element": {
            "type": "plain_text_input",
            "action_id": "set_user_first_name",
            "placeholder": {"type": "plain_text", "text": "Add your first name"},
        },
    }
    if first_name:
        first_name_input["element"]["initial_value"] = first_name

    last_name_input = {
        "type": "input",
        "block_id": "profile_last_name",
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "Last name", "emoji": True},
        "element": {
            "type": "plain_text_input",
            "action_id": "set_user_last_name",
            "placeholder": {"type": "plain_text", "text": "Add your last name"},
        },
    }
    if last_name:
        last_name_input["element"]["initial_value"] = last_name

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Welcome to Bolty's Home Page!",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Your Profile*\nSet how Bolty addresses you in responses. "
                    "Leave blank to skip."
                ),
            },
        },
        first_name_input,
        last_name_input,
        {"type": "divider"},
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_section",
                    "elements": [
                        {
                            "type": "text",
                            "text": "Pick an option",
                            "style": {"bold": True},
                        }
                    ],
                }
            ],
        },
        {
            "type": "actions",
            "elements": [provider_select],
        },
    ]

    if platform_selection_element:
        blocks.extend(
            [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Management Platforms*\nSelect the project management tools you "
                            "want Bolty to use when helping you."
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [platform_selection_element],
                },
            ]
        )

    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Personal Rules*\nThese instructions guide Bolty's responses.",
                },
            },
        ]
    )

    if rules:
        for rule in rules:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"- {rule}"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Delete", "emoji": True},
                        "style": "danger",
                        "action_id": RULE_ACTION_DELETE,
                        "value": rule,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Delete rule?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": "Are you sure you want to remove this rule?",
                            },
                            "confirm": {"type": "plain_text", "text": "Delete"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                }
            )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "You haven't added any rules yet. Use `/rule` in Slack to create one."
                        ),
                    }
                ],
            }
        )

    return {"type": "home", "blocks": blocks}
