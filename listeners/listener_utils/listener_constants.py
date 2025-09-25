# This file defines constant messages used by the Slack bot for when a user mentions the bot without text,
# when summarizing a channel's conversation history, and a default loading message.
# Used in `app_mentioned_callback`, `dm_sent_callback`, and `handle_summary_function_callback`.

MENTION_WITHOUT_TEXT = """
Hi there! You didn't provide a message with your mention.
    Mention me again in this thread so that I can help you out!
"""
SUMMARIZE_CHANNEL_WORKFLOW = """
A user has just joined this Slack channel.
Please create a quick summary of the conversation in this channel to help them catch up.
Don't use user IDs or names in your response.
"""
DEFAULT_LOADING_TEXT = "Thinking..."

APPROVAL_ACTION_APPROVE = "approval_request_approve"
APPROVAL_ACTION_REJECT = "approval_request_reject"
APPROVAL_ACTION_EDIT = "approval_request_edit"
APPROVAL_EDIT_MODAL_CALLBACK = "approval_request_edit_modal"
QUESTION_ACTION_OPEN_MODAL = "ask_tool_open_modal"
QUESTION_MODAL_CALLBACK = "ask_tool_modal_submit"
QUESTION_MODAL_INPUT_BLOCK = "ask_tool_answer_block"
QUESTION_MODAL_INPUT_ACTION = "ask_tool_answer_input"
FORGET_ACTION_DELETE = "memory_forget_delete"
FORGET_ACTION_SKIP = "memory_forget_skip"
