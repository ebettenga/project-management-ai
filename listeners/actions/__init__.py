from slack_bolt import App

from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
    APPROVAL_EDIT_MODAL_CALLBACK,
)

from .approval_actions import (
    approve_request,
    reject_request,
    start_edit_request,
    submit_edit_request,
)
from .set_user_selection import set_user_selection


def register(app: App):
    app.action("pick_a_provider")(set_user_selection)
    app.action(APPROVAL_ACTION_APPROVE)(approve_request)
    app.action(APPROVAL_ACTION_REJECT)(reject_request)
    app.action(APPROVAL_ACTION_EDIT)(start_edit_request)
    app.view(APPROVAL_EDIT_MODAL_CALLBACK)(submit_edit_request)
