from analint import Invariant
from .entities import (
    Board, BoardStatus, Card, CardStatus, Column, Comment,
    MemberRole, Membership, Notification, NotificationStatus, User,
)

# ── World invariants — hold in every state ─────────────────────────────────────

user_is_active = Invariant(
    User.is_active == True,  # noqa: E712
    label="User must be active",
)

# ── Reusable predicates — plain expressions shared by actions ──────────────────

board_is_active         = Board.status == BoardStatus.ACTIVE
membership_on_board     = Membership.board_id == Board.id
acting_membership       = Membership.user_id == User.id
card_on_board           = Card.board_id == Board.id
card_not_archived       = Card.status != CardStatus.ARCHIVED
column_on_board         = Column.board_id == Board.id
assignee_is_member      = Membership.user_id == Card.assignee_id
acting_as_owner         = Membership.role == MemberRole.OWNER
comment_author_on_board = Membership.user_id == Comment.author_id
notification_unread     = Notification.status == NotificationStatus.UNREAD
