from slack_bolt import App

from .ask_llm import llm_callback
from .memory_commands import remember_callback, ask_memory_callback, forget_memory_callback


def register(app: App):
    app.command("/ask-llm")(llm_callback)
    app.command("/remember")(remember_callback)
    app.command("/ask")(ask_memory_callback)
    app.command("/forget")(forget_memory_callback)
