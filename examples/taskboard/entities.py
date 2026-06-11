from enum import StrEnum

from analint import Entity, Field, Lifecycle, Transition


class MemberRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"
    VIEWER = "viewer"


class BoardStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CardStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ARCHIVED = "archived"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NotificationStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"


class User(Entity):
    id: str
    email: str
    is_active: bool = True


class Board(Entity):
    id: str
    owner_id: str
    status: BoardStatus = Lifecycle(
        initial=BoardStatus.ACTIVE,
        transitions=[
            Transition(BoardStatus.ACTIVE, [BoardStatus.ARCHIVED]),
        ],
        terminal=[BoardStatus.ARCHIVED],
    )
    card_count: int = Field(0, ge=0)


class Membership(Entity):
    user_id: str
    board_id: str
    role: MemberRole = MemberRole.MEMBER


class Column(Entity):
    id: str
    board_id: str


class Card(Entity):
    id: str
    board_id: str
    column_id: str
    creator_id: str
    assignee_id: str = ""
    status: CardStatus = Lifecycle(
        initial=CardStatus.TODO,
        transitions=[
            Transition(CardStatus.TODO, [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
            Transition(CardStatus.IN_PROGRESS, [CardStatus.DONE, CardStatus.ARCHIVED]),
            Transition(CardStatus.DONE, [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
        ],
        terminal=[CardStatus.ARCHIVED],
    )
    priority: Priority = Priority.MEDIUM
    comment_count: int = Field(0, ge=0)


class Comment(Entity):
    id: str
    card_id: str
    author_id: str


class Notification(Entity):
    id: str
    recipient_id: str
    status: NotificationStatus = Lifecycle(
        initial=NotificationStatus.UNREAD,
        transitions=[
            Transition(NotificationStatus.UNREAD, [NotificationStatus.READ]),
        ],
        terminal=[NotificationStatus.READ],
    )
