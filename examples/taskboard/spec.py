from analint import Spec

# The entry point's import graph defines what is in the spec:
# scenarios pull in actions → invariants/entities/actors/events.
from . import flows, lifecycles, scenarios  # noqa: F401

spec = Spec(
    id="taskboard",
    name="Task Board (Trello-like)",
    version="1.0.0",
    description="Boards, cards, members, comments, notifications, async queue consumers",
)
