from analint import Set, Subtract, Add, UseCase
from examples.taskboard.actors import Member, Owner, System
from examples.taskboard.entities import (
    Board, Card, CardStatus, Column, Comment, Membership,
    Notification, NotificationStatus, User,
)
from examples.taskboard.events import (
    CardAssigned, CardCreated, CardMoved, CommentAdded,
    MemberInvited, NotificationDelivered,
)
from examples.taskboard.rules import (
    rule_assignee_is_member, rule_board_active, rule_board_count_incremented,
    rule_card_archived_after, rule_card_not_archived, rule_card_on_board,
    rule_column_on_board, rule_comment_author_on_board, rule_membership_matches_board,
    rule_membership_matches_user, rule_notification_read_after, rule_notification_unread,
    rule_owner_role, rule_user_active,
)

uc_invite_member = UseCase(
    id="invite-member",
    name="Invite Member to Board",
    actor=Owner,
    entities=[User, Board, Membership],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_membership_matches_user,
        rule_board_active,
        rule_owner_role,
    ],
    emits=[MemberInvited],
)

uc_create_card = UseCase(
    id="create-card",
    name="Create Card",
    actor=Member,
    entities=[User, Board, Membership, Column, Card],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_membership_matches_user,
        rule_board_active,
        rule_column_on_board,
        rule_board_count_incremented,
    ],
    emits=[CardCreated],
    effects=[Add(Board.card_count, 1)],
)

uc_move_card = UseCase(
    id="move-card",
    name="Move Card to Column",
    actor=Member,
    entities=[User, Board, Membership, Card, Column],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_membership_matches_user,
        rule_board_active,
        rule_card_on_board,
        rule_card_not_archived,
    ],
    emits=[CardMoved],
    effects=[
        Set(Card.column_id, Column.id),
        Set(Card.status, CardStatus.IN_PROGRESS),
    ],
    requires=[uc_create_card],
)

uc_assign_card = UseCase(
    id="assign-card",
    name="Assign Card to Member",
    actor=Member,
    entities=[User, Board, Membership, Card],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_board_active,
        rule_card_on_board,
        rule_card_not_archived,
        rule_assignee_is_member,
    ],
    emits=[CardAssigned],
    effects=[Set(Card.assignee_id, Membership.user_id)],
    requires=[uc_create_card],
)

uc_add_comment = UseCase(
    id="add-comment",
    name="Add Comment to Card",
    actor=Member,
    entities=[User, Board, Membership, Card, Comment],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_membership_matches_user,
        rule_board_active,
        rule_card_on_board,
        rule_card_not_archived,
        rule_comment_author_on_board,
    ],
    emits=[CommentAdded],
    effects=[Add(Card.comment_count, 1)],
    requires=[uc_create_card],
)

uc_archive_card = UseCase(
    id="archive-card",
    name="Archive Card",
    actor=Member,
    entities=[User, Board, Membership, Card],
    rules=[
        rule_user_active,
        rule_membership_matches_board,
        rule_membership_matches_user,
        rule_board_active,
        rule_card_on_board,
        rule_card_not_archived,
        rule_card_archived_after,
    ],
    effects=[
        Set(Card.status, CardStatus.ARCHIVED),
        Subtract(Board.card_count, 1),
    ],
    requires=[uc_create_card],
)

uc_send_notification = UseCase(
    id="send-notification",
    name="Send Notification",
    actor=System,
    entities=[Notification],
    rules=[rule_notification_unread, rule_notification_read_after],
    triggered_by=[CardCreated, CardAssigned, CommentAdded, MemberInvited],
    emits=[NotificationDelivered],
    effects=[Set(Notification.status, NotificationStatus.READ)],
)

uc_read_notification = UseCase(
    id="read-notification",
    name="Mark Notification as Read",
    actor=Member,
    entities=[User, Notification],
    rules=[rule_user_active, rule_notification_unread, rule_notification_read_after],
    effects=[Set(Notification.status, NotificationStatus.READ)],
    requires=[uc_send_notification],
)
