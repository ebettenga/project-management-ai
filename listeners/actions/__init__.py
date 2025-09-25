from slack_bolt import App

from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
    APPROVAL_EDIT_MODAL_CALLBACK,
    QUESTION_ACTION_OPEN_MODAL,
    QUESTION_MODAL_CALLBACK,
    FORGET_ACTION_DELETE,
    FORGET_ACTION_SKIP,
)

from .approval_actions import (
    approve_request,
    reject_request,
    start_edit_request,
    submit_edit_request,
)
from .set_user_selection import set_user_selection
from .question_actions import open_question_modal, submit_question_modal
from .memory_forget_actions import delete_memory_request, skip_memory_request


def register(app: App):
    app.action("pick_a_provider")(set_user_selection)
    app.action(APPROVAL_ACTION_APPROVE)(approve_request)
    app.action(APPROVAL_ACTION_REJECT)(reject_request)
    app.action(APPROVAL_ACTION_EDIT)(start_edit_request)
    app.view(APPROVAL_EDIT_MODAL_CALLBACK)(submit_edit_request)
    app.action(QUESTION_ACTION_OPEN_MODAL)(open_question_modal)
    app.view(QUESTION_MODAL_CALLBACK)(submit_question_modal)
    app.action(FORGET_ACTION_DELETE)(delete_memory_request)
    app.action(FORGET_ACTION_SKIP)(skip_memory_request)
