from analint import Contract, Spec

from .actions import (
    add_comment,
    archive_card,
    assign_card,
    create_card,
    invite_member,
    move_card,
    read_notification,
    send_notification,
)
from .flows import flow_onboarding
from .scenarios import (
    sc_archive_already_archived,
    sc_archive_ok,
    sc_assign_nonmember,
    sc_assign_ok,
    sc_comment_archived_card,
    sc_comment_ok,
    sc_create_card_archived_board,
    sc_create_card_ok,
    sc_create_card_wrong_board,
    sc_invite_inactive_user,
    sc_invite_not_owner,
    sc_invite_ok,
    sc_move_archived_card,
    sc_move_card_ok,
    sc_notification_already_read,
    sc_notification_delivered,
)

# One Contract per process. The model is exactly what the Spec and its
# contracts list; entities, events and lifecycles follow by reference.
membership = Contract(
    id="membership",
    actions=[invite_member],
    scenarios=[sc_invite_ok, sc_invite_not_owner, sc_invite_inactive_user],
)
cards = Contract(
    id="cards",
    actions=[create_card, move_card, assign_card, add_comment, archive_card],
    scenarios=[
        sc_create_card_ok,
        sc_create_card_archived_board,
        sc_create_card_wrong_board,
        sc_move_card_ok,
        sc_move_archived_card,
        sc_assign_ok,
        sc_assign_nonmember,
        sc_comment_ok,
        sc_comment_archived_card,
        sc_archive_ok,
        sc_archive_already_archived,
    ],
)
notifications = Contract(
    id="notifications",
    actions=[send_notification, read_notification],
    scenarios=[sc_notification_delivered, sc_notification_already_read],
)

spec = Spec(
    id="taskboard",
    name="Task Board (Trello-like)",
    version="1.0.0",
    description="Boards, cards, members, comments, notifications, async queue consumers",
    imports=[membership, cards, notifications],
    flows=[flow_onboarding],
)
