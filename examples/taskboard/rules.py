from analint import BusinessRule, RuleType
from examples.taskboard.entities import (
    BoardStatus, Card, CardStatus, Column, Comment, MemberRole,
    Membership, Board, Notification, NotificationStatus, User,
)

rule_user_active = BusinessRule(
    id="user-active",
    name="User must be active",
    rule_type=RuleType.INVARIANT,
    expression=User.is_active == True,  # noqa: E712
)

rule_membership_matches_board = BusinessRule(
    id="membership-matches-board",
    name="Membership must reference the correct board",
    rule_type=RuleType.INVARIANT,
    expression=Membership.board_id == Board.id,
)

rule_membership_matches_user = BusinessRule(
    id="membership-matches-user",
    name="Membership must reference the acting user",
    rule_type=RuleType.INVARIANT,
    expression=Membership.user_id == User.id,
)

rule_board_active = BusinessRule(
    id="board-active",
    name="Board must be active",
    rule_type=RuleType.PRECONDITION,
    expression=Board.status == BoardStatus.ACTIVE,
)

rule_card_on_board = BusinessRule(
    id="card-on-board",
    name="Card must belong to the board",
    rule_type=RuleType.PRECONDITION,
    expression=Card.board_id == Board.id,
)

rule_card_not_archived = BusinessRule(
    id="card-not-archived",
    name="Card must not be already archived",
    rule_type=RuleType.PRECONDITION,
    expression=Card.status != CardStatus.ARCHIVED,
)

rule_column_on_board = BusinessRule(
    id="column-on-board",
    name="Target column must belong to the same board",
    rule_type=RuleType.PRECONDITION,
    expression=Column.board_id == Board.id,
)

rule_assignee_is_member = BusinessRule(
    id="assignee-is-member",
    name="Assignee must be a board member",
    rule_type=RuleType.PRECONDITION,
    expression=Membership.user_id == Card.assignee_id,
)

rule_owner_role = BusinessRule(
    id="owner-role",
    name="Only board owner can perform this action",
    rule_type=RuleType.PRECONDITION,
    expression=Membership.role == MemberRole.OWNER,
)

rule_comment_author_on_board = BusinessRule(
    id="comment-author-on-board",
    name="Comment author must be a board member",
    rule_type=RuleType.PRECONDITION,
    expression=Membership.user_id == Comment.author_id,
)

rule_notification_unread = BusinessRule(
    id="notification-unread",
    name="Notification must be unread before marking as read",
    rule_type=RuleType.PRECONDITION,
    expression=Notification.status == NotificationStatus.UNREAD,
)

rule_card_archived_after = BusinessRule(
    id="card-archived-after",
    name="Card must be archived after the archive operation",
    rule_type=RuleType.POSTCONDITION,
    expression=Card.status == CardStatus.ARCHIVED,
)

rule_board_count_incremented = BusinessRule(
    id="board-count-incremented",
    name="Board card count must increase after card creation",
    rule_type=RuleType.POSTCONDITION,
    expression=Board.card_count > 0,
)

rule_notification_read_after = BusinessRule(
    id="notification-read-after",
    name="Notification must be read after marking",
    rule_type=RuleType.POSTCONDITION,
    expression=Notification.status == NotificationStatus.READ,
)
