from analint import StateMachine, Transition
from examples.taskboard.entities import (
    Board, BoardStatus, Card, CardStatus, Notification, NotificationStatus,
)

card_lifecycle = StateMachine(
    id="card-lifecycle",
    field=Card.status,
    initial=CardStatus.TODO,
    transitions=[
        Transition(CardStatus.TODO,        [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
        Transition(CardStatus.IN_PROGRESS, [CardStatus.DONE, CardStatus.ARCHIVED]),
        Transition(CardStatus.DONE,        [CardStatus.IN_PROGRESS, CardStatus.ARCHIVED]),
    ],
)

board_lifecycle = StateMachine(
    id="board-lifecycle",
    field=Board.status,
    initial=BoardStatus.ACTIVE,
    transitions=[
        Transition(BoardStatus.ACTIVE, BoardStatus.ARCHIVED),
    ],
)

notification_lifecycle = StateMachine(
    id="notification-lifecycle",
    field=Notification.status,
    initial=NotificationStatus.UNREAD,
    transitions=[
        Transition(NotificationStatus.UNREAD, NotificationStatus.READ),
    ],
)
