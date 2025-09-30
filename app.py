import asyncio
import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from config import get_settings
from langgraph.checkpoint.postgres import PostgresSaver
from listeners import register_listeners


settings = get_settings()

if settings.debug:
    import debugpy

    debugpy.listen(("0.0.0.0", 5678))

db_uri = settings.postgres_url
if not db_uri:
    raise RuntimeError("POSTGRES_URL is not configured")

with PostgresSaver.from_conn_string(db_uri) as checkpointer:
    checkpointer.setup()

# Initialization
if not settings.slack_bot_token:
    raise RuntimeError("SLACK_BOT_TOKEN is not configured")

app = AsyncApp(token=settings.slack_bot_token)
logging.basicConfig(level=logging.DEBUG)

# Register Listeners
register_listeners(app)


async def main():
    if not settings.slack_app_token:
        raise RuntimeError("SLACK_APP_TOKEN is not configured")

    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    await handler.start_async()


# Start Bolt app
if __name__ == "__main__":
    asyncio.run(main())
