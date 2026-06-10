from analint import Lifecycle, Transition
from .entities import (
    Board, BoardStatus, Card, CardStatus, Notification, NotificationStatus,
)

card_lifecycle = Lifecycle(
    field=Card.status,
    initial=CardStatus.TODO,
    transitions=[
        Transition(CardStatus.TODO,        [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
        Transition(CardStatus.IN_PROGRESS, [CardStatus.DONE, CardStatus.ARCHIVED]),
        Transition(CardStatus.DONE,        [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
    ],
    terminal=[CardStatus.ARCHIVED],
)

board_lifecycle = Lifecycle(
    field=Board.status,
    initial=BoardStatus.ACTIVE,
    transitions=[
        Transition(BoardStatus.ACTIVE, BoardStatus.ARCHIVED),
    ],
    terminal=[BoardStatus.ARCHIVED],
)

notification_lifecycle = Lifecycle(
    field=Notification.status,
    initial=NotificationStatus.UNREAD,
    transitions=[
        Transition(NotificationStatus.UNREAD, NotificationStatus.READ),
    ],
    terminal=[NotificationStatus.READ],
)
