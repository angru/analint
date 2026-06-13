from .entities import (
    Board,
    BoardStatus,
    Card,
    CardStatus,
    Column,
    Comment,
    MemberRole,
    Membership,
    Notification,
    NotificationStatus,
    User,
)

# ── Reusable predicates — plain expressions shared by actions ──────────────────

# An inactive user cannot act. This is a guard on the acting user, not a world
# invariant: the world legitimately contains inactive users, so "every user is
# active" is false as an invariant — it would make any such state illegal.
acting_user_is_active = User.is_active == True  # noqa: E712
board_is_active = Board.status == BoardStatus.ACTIVE
membership_on_board = Membership.board_id == Board.id
acting_membership = Membership.user_id == User.id
card_on_board = Card.board_id == Board.id
card_not_archived = Card.status != CardStatus.ARCHIVED
column_on_board = Column.board_id == Board.id
assignee_is_member = Membership.user_id == Card.assignee_id
acting_as_owner = Membership.role == MemberRole.OWNER
comment_author_on_board = Membership.user_id == Comment.author_id
notification_unread = Notification.status == NotificationStatus.UNREAD
