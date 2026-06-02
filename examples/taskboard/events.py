from analint import Event


class CardCreated(Event):
    card_id: str
    board_id: str
    creator_id: str

class CardMoved(Event):
    card_id: str
    to_column_id: str

class CardAssigned(Event):
    card_id: str
    assignee_id: str

class CommentAdded(Event):
    card_id: str
    comment_id: str
    author_id: str

class MemberInvited(Event):
    board_id: str
    user_id: str
    role: str

class NotificationDelivered(Event):
    notification_id: str
    recipient_id: str
