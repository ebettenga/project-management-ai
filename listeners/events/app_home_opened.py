from logging import Logger
from ai.providers import get_available_providers
from slack_sdk import WebClient
from state_store.get_user_state import get_user_state
from listeners.user_management_platforms import (
    get_user_management_platforms,
    list_management_platforms,
)

"""
Callback for handling the 'app_home_opened' event. It checks if the event is for the 'home' tab,
generates a list of model options for a dropdown menu, retrieves the user's state to set the initial option,
and publishes a view to the user's home tab in Slack.
"""


async def app_home_opened_callback(event: dict, logger: Logger, client: WebClient):
    if event["tab"] != "home":
        return

    user_id = event["user"]

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
        initial_model = get_user_state(user_id, True)[1]
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

    try:
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

        await client.views_publish(
            user_id=user_id,
            view={
                "type": "home",
                "blocks": blocks,
            },
        )
    except Exception as e:
        logger.error(e)
