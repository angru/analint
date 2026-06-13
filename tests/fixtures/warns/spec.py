"""A spec that always emits exactly one structural warning (an action with no
scenario) — a stable fixture for --strict behaviour, independent of any example."""

from analint import Action, Entity, Field, Set, Spec


class Box(Entity):
    open: bool = Field(False)


# no scenario covers this action -> guaranteed "has no scenarios" warning
toggle = Action(id="toggle", pre=[Box.open == False], effect=[Set(Box.open, True)])  # noqa: E712

spec = Spec(id="warns", name="Warns")
