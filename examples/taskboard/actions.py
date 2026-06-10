from analint import Action, Add, Set, Subtract
from .actors import Member, Owner, System
from .entities import (
    Board, Card, CardStatus, Column, Membership, Notification, NotificationStatus,
)
from .events import (
    CardAssigned, CardCreated, CardMoved, CommentAdded,
    MemberInvited, NotificationDelivered,
)
from .invariants import (
    acting_as_owner, acting_membership, assignee_is_member, board_is_active,
    card_not_archived, card_on_board, column_on_board, comment_author_on_board,
    membership_on_board, notification_unread,
)

invite_member = Action(
    name="Invite Member to Board",
    by=Owner,
    pre=[board_is_active, membership_on_board, acting_membership, acting_as_owner],
    emits=[MemberInvited(board_id=Board.id, user_id=Membership.user_id,
                         role=Membership.role)],
)

create_card = Action(
    name="Create Card",
    by=Member,
    pre=[board_is_active, membership_on_board, acting_membership, column_on_board],
    effect=[Add(Board.card_count, 1)],
    post=[Board.card_count > 0],
    emits=[CardCreated(card_id=Card.id, board_id=Board.id, creator_id=Card.creator_id)],
)

move_card = Action(
    name="Move Card to Column",
    by=Member,
    pre=[board_is_active, membership_on_board, acting_membership,
         card_on_board, card_not_archived],
    effect=[
        Set(Card.column_id, Column.id),
        Set(Card.status, CardStatus.IN_PROGRESS),
    ],
    emits=[CardMoved(card_id=Card.id, to_column_id=Column.id)],
    requires=[create_card],
)

assign_card = Action(
    name="Assign Card to Member",
    by=Member,
    pre=[board_is_active, membership_on_board,
         card_on_board, card_not_archived, assignee_is_member],
    effect=[Set(Card.assignee_id, Membership.user_id)],
    emits=[CardAssigned(card_id=Card.id, assignee_id=Membership.user_id)],
    requires=[create_card],
)

add_comment = Action(
    name="Add Comment to Card",
    by=Member,
    pre=[board_is_active, membership_on_board, acting_membership,
         card_on_board, card_not_archived, comment_author_on_board],
    effect=[Add(Card.comment_count, 1)],
    emits=[CommentAdded(card_id=Card.id, comment_id=Card.id, author_id=Card.creator_id)],
    requires=[create_card],
)

archive_card = Action(
    name="Archive Card",
    by=Member,
    pre=[board_is_active, membership_on_board, acting_membership,
         card_on_board, card_not_archived],
    effect=[
        Set(Card.status, CardStatus.ARCHIVED),
        Subtract(Board.card_count, 1),
    ],
    post=[Card.status == CardStatus.ARCHIVED],
    requires=[create_card],
)

send_notification = Action(
    name="Send Notification",
    by=System,
    on=[CardCreated, CardAssigned, CommentAdded, MemberInvited],
    pre=[notification_unread],
    effect=[Set(Notification.status, NotificationStatus.READ)],
    post=[Notification.status == NotificationStatus.READ],
    emits=[NotificationDelivered(notification_id=Notification.id,
                                 recipient_id=Notification.recipient_id)],
)

read_notification = Action(
    name="Mark Notification as Read",
    by=Member,
    pre=[notification_unread],
    effect=[Set(Notification.status, NotificationStatus.READ)],
    post=[Notification.status == NotificationStatus.READ],
    requires=[send_notification],
)
