from enum import Enum
from analint import Entity


class MemberRole(Enum):
    OWNER  = "owner"
    MEMBER = "member"
    VIEWER = "viewer"

class BoardStatus(Enum):
    ACTIVE   = "active"
    ARCHIVED = "archived"

class CardStatus(Enum):
    TODO        = "todo"
    IN_PROGRESS = "in_progress"
    DONE        = "done"
    ARCHIVED    = "archived"

class Priority(Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"

class NotificationStatus(Enum):
    UNREAD = "unread"
    READ   = "read"


class User(Entity):
    id: str
    email: str
    is_active: bool = True

class Board(Entity):
    id: str
    owner_id: str
    status: BoardStatus = BoardStatus.ACTIVE
    card_count: int = 0

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
    status: CardStatus = CardStatus.TODO
    priority: Priority = Priority.MEDIUM
    comment_count: int = 0

class Comment(Entity):
    id: str
    card_id: str
    author_id: str

class Notification(Entity):
    id: str
    recipient_id: str
    status: NotificationStatus = NotificationStatus.UNREAD
