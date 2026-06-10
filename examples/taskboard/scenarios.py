from analint import Assert, Emitted, Expect, Scenario
from .entities import (
    Board, BoardStatus, Card, CardStatus, Column, Comment,
    MemberRole, Membership, Notification, NotificationStatus, User,
)
from .events import (
    CardAssigned, CardCreated, CardMoved, CommentAdded, NotificationDelivered,
)
from .actions import (
    add_comment, archive_card, assign_card,
    create_card, invite_member, move_card, send_notification,
)

# helpers
def _active_board(id="b1"):
    return Board(id=id, owner_id="u1", status=BoardStatus.ACTIVE, card_count=0)

def _owner_membership(user_id="u1", board_id="b1"):
    return Membership(user_id=user_id, board_id=board_id, role=MemberRole.OWNER)

def _member_membership(user_id="u2", board_id="b1"):
    return Membership(user_id=user_id, board_id=board_id, role=MemberRole.MEMBER)

def _active_user(id="u1"):
    return User(id=id, email=f"{id}@example.com", is_active=True)

def _active_card(board_id="b1", column_id="col-todo", status=CardStatus.TODO):
    return Card(id="c1", board_id=board_id, column_id=column_id,
                creator_id="u1", status=status)

def _column(id="col-inprogress", board_id="b1"):
    return Column(id=id, board_id=board_id)


# ── invite-member ──

sc_invite_ok = Scenario(
    id="invite-member/happy",
    name="Owner successfully invites a new member",
    action=invite_member,
    given=[_active_user("u1"), _active_board(), _owner_membership("u1", "b1")],
    expected=Expect.PASS,
)

sc_invite_not_owner = Scenario(
    id="invite-member/not-owner",
    name="Non-owner cannot invite members",
    action=invite_member,
    given=[_active_user("u2"), _active_board(), _member_membership("u2", "b1")],
    expected=Expect.FAIL,
)

sc_invite_inactive_user = Scenario(
    id="invite-member/inactive-user",
    name="Inactive user cannot perform any action",
    action=invite_member,
    given=[
        User(id="u99", email="u99@example.com", is_active=False),
        _active_board(),
        Membership(user_id="u99", board_id="b1", role=MemberRole.OWNER),
    ],
    expected=Expect.FAIL,
)

# ── create-card ──

sc_create_card_ok = Scenario(
    id="create-card/happy",
    name="Member creates a card in a column",
    action=create_card,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _column("col-todo", "b1"),
        _active_card("b1", "col-todo"),
    ],
    then=[Assert(Board.card_count == 1), Emitted(CardCreated)],
    expected=Expect.PASS,
)

sc_create_card_archived_board = Scenario(
    id="create-card/archived-board",
    name="Cannot create card on archived board",
    action=create_card,
    given=[
        _active_user("u2"),
        Board(id="b1", owner_id="u1", status=BoardStatus.ARCHIVED, card_count=0),
        _member_membership("u2", "b1"),
        _column("col-todo", "b1"),
        _active_card("b1", "col-todo"),
    ],
    expected=Expect.FAIL,
)

sc_create_card_wrong_board = Scenario(
    id="create-card/column-wrong-board",
    name="Column belongs to a different board — blocked",
    action=create_card,
    given=[
        _active_user("u2"),
        _active_board("b1"),
        _member_membership("u2", "b1"),
        Column(id="col-other", board_id="b99"),
        _active_card("b1", "col-other"),
    ],
    expected=Expect.FAIL,
)

# ── move-card ──

sc_move_card_ok = Scenario(
    id="move-card/happy",
    name="Member moves a card from TODO to IN_PROGRESS",
    action=move_card,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-todo", CardStatus.TODO),
        _column("col-inprogress", "b1"),
    ],
    then=[
        Assert(Card.status == CardStatus.IN_PROGRESS),
        Assert(Card.column_id == "col-inprogress"),
        Emitted(CardMoved),
    ],
    expected=Expect.PASS,
)

sc_move_archived_card = Scenario(
    id="move-card/already-archived",
    name="Archived cards cannot be moved",
    action=move_card,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-todo", CardStatus.ARCHIVED),
        _column("col-inprogress", "b1"),
    ],
    expected=Expect.FAIL,
)

# ── assign-card ──

sc_assign_ok = Scenario(
    id="assign-card/happy",
    name="Assign card to a board member",
    action=assign_card,
    given=[
        _active_user("u1"),
        _active_board(),
        Membership(user_id="u2", board_id="b1", role=MemberRole.MEMBER),
        Card(id="c1", board_id="b1", column_id="col-todo",
             creator_id="u1", assignee_id="u2", status=CardStatus.TODO),
    ],
    then=[Assert(Card.assignee_id == "u2"), Emitted(CardAssigned)],
    expected=Expect.PASS,
)

sc_assign_nonmember = Scenario(
    id="assign-card/not-a-member",
    name="Cannot assign card to someone not on the board",
    action=assign_card,
    given=[
        _active_user("u1"),
        _active_board(),
        Membership(user_id="u99", board_id="b1", role=MemberRole.MEMBER),
        Card(id="c1", board_id="b1", column_id="col-todo",
             creator_id="u1", assignee_id="u2", status=CardStatus.TODO),
    ],
    expected=Expect.FAIL,
)

# ── add-comment ──

sc_comment_ok = Scenario(
    id="add-comment/happy",
    name="Member adds a comment to a card",
    action=add_comment,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-todo"),
        Comment(id="cm1", card_id="c1", author_id="u2"),
    ],
    then=[Assert(Card.comment_count == 1), Emitted(CommentAdded)],
    expected=Expect.PASS,
)

sc_comment_archived_card = Scenario(
    id="add-comment/archived-card",
    name="Cannot comment on archived card",
    action=add_comment,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-todo", CardStatus.ARCHIVED),
        Comment(id="cm1", card_id="c1", author_id="u2"),
    ],
    expected=Expect.FAIL,
)

# ── archive-card ──

sc_archive_ok = Scenario(
    id="archive-card/happy",
    name="Member archives a card; board counter decrements",
    action=archive_card,
    given=[
        _active_user("u2"),
        Board(id="b1", owner_id="u1", status=BoardStatus.ACTIVE, card_count=3),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-inprogress", CardStatus.IN_PROGRESS),
    ],
    then=[Assert(Card.status == CardStatus.ARCHIVED), Assert(Board.card_count == 2)],
    expected=Expect.PASS,
)

sc_archive_already_archived = Scenario(
    id="archive-card/already-archived",
    name="Archiving an already-archived card is blocked",
    action=archive_card,
    given=[
        _active_user("u2"),
        _active_board(),
        _member_membership("u2", "b1"),
        _active_card("b1", "col-todo", CardStatus.ARCHIVED),
    ],
    expected=Expect.FAIL,
)

# ── send-notification ──

sc_notification_delivered = Scenario(
    id="send-notification/happy",
    name="System delivers an unread notification",
    action=send_notification,
    given=[Notification(id="n1", recipient_id="u2", status=NotificationStatus.UNREAD)],
    then=[Assert(Notification.status == NotificationStatus.READ), Emitted(NotificationDelivered)],
    expected=Expect.PASS,
)

sc_notification_already_read = Scenario(
    id="send-notification/already-read",
    name="System skips already-read notifications",
    action=send_notification,
    given=[Notification(id="n1", recipient_id="u2", status=NotificationStatus.READ)],
    expected=Expect.FAIL,
)
