# taskboard — a Trello-like board with async notifications

## Purpose & source
An invented collaboration domain (no external source): boards, cards, members,
comments, notifications and asynchronous queue consumers. The model is composed
from `flows` and `scenarios` modules via the entry point.

## Modeled scope & omissions
Card lifecycle and movement, notification delivery and reading via an async queue.
Real concurrency/timing of the queue is out of scope (bounded reachability).

## Key entities / actions / properties
- Boards/cards/members/comments/notifications; events `CardMoved`,
  `NotificationDelivered`.
- Flows and scenarios exercising the board and the notification queue.

## Run
```
uv run analint check examples/taskboard
```

## Expected outcome
PASS, exit 0, with one intentional warning:
- `action:read_notification` — has no scenarios.

## What a behavioural change means
Adding a `read_notification` scenario would clear the warning. A new failing
query would indicate a board/queue behaviour regression.

## Related research
research/30 (subtractive public-API cleanup).
