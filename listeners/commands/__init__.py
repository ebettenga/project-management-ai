from slack_bolt import App

from .ask_llm import llm_callback
from .clear_thread import clear_thread_command
from .rule import rule_callback
from .memory_commands import remember_callback, ask_memory_callback, forget_memory_callback


def register(app: App):
    app.command("/ask-llm")(llm_callback)
    app.command("/clear")(clear_thread_command)
    app.command("/rule")(rule_callback)
    app.command("/remember")(remember_callback)
    app.command("/ask")(ask_memory_callback)
    app.command("/forget")(forget_memory_callback)
