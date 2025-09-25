import os
import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from dotenv import load_dotenv
import asyncio
from listeners import register_listeners

load_dotenv()

# Initialization
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
logging.basicConfig(level=logging.DEBUG)

# Register Listeners
register_listeners(app)


async def main():
    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


# Start Bolt app
if __name__ == "__main__":
    asyncio.run(main())
