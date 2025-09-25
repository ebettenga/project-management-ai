import os
import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from dotenv import load_dotenv
import asyncio
from listeners import register_listeners
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

DB_URI = os.getenv("POSTGRES_URL")
with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    checkpointer.setup()

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
