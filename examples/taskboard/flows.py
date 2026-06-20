from analint import Assert, Emitted, Flow

from .actions import (
    create_card,
    invite_member,
)
from .entities import (
    Board,
    BoardStatus,
    Card,
    CardStatus,
    Column,
    MemberRole,
    Membership,
    User,
)
from .events import CardCreated, MemberInvited

# An executable journey: a fixed initial board, then the owner invites a member
# and creates the first card. Each action runs through the transition kernel —
# its post-state feeds the next — and the checkpoints assert the result.
flow_onboarding = Flow(
    id="board-onboarding",
    given=[
        User(id="u1", email="u1@example.com", is_active=True),
        Board(id="b1", owner_id="u1", status=BoardStatus.ACTIVE, card_count=0),
        Membership(user_id="u1", board_id="b1", role=MemberRole.OWNER),
        Column(id="col-todo", board_id="b1"),
        Card(id="c1", board_id="b1", column_id="col-todo", creator_id="u1", status=CardStatus.TODO),
    ],
    steps=[
        invite_member,
        Emitted(MemberInvited),
        create_card,
        Assert(Board.card_count == 1),
        Emitted(CardCreated),
    ],
    description="Owner sets up a board: invite a member, create the first card",
)
