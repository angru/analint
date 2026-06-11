from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from analint.models.entity import FieldDescriptor

S = TypeVar("S")  # the state type (usually an Enum)


@dataclass
class Transition(Generic[S]):
    """One allowed group of state transitions for an entity field.

    `to_states` is always a collection (a single target is a one-element list):

        Transition(PENDING, [PAID, CANCELLED])
        Transition(PAID, [CANCELLED])
    """

    from_state: S
    to_states: tuple[S, ...]

    def __init__(self, from_state: S, to_states: Iterable[S]) -> None:
        if isinstance(to_states, (str, bytes)) or not isinstance(to_states, Iterable):
            raise TypeError(
                f"Transition to_states must be a collection — write "
                f"Transition({from_state!r}, [{to_states!r}])"
            )
        self.from_state = from_state
        self.to_states = tuple(to_states)


@dataclass
class Lifecycle(Generic[S]):
    """The lifecycle of an entity field, declared as the field's default value:

        class Card(Entity):
            status: CardStatus = Lifecycle(
                initial=CardStatus.TODO,
                transitions=[Transition(CardStatus.TODO, [CardStatus.DONE])],
                terminal=[CardStatus.DONE],
            )

    The field's default value is `initial`. `terminal` states have no way out:
    an entity in a terminal state cannot be modified by any action.
    `entity_cls` and `field_name` are wired by the Entity metaclass.
    """

    initial: S
    transitions: list[Transition[S]] = field(default_factory=list)
    terminal: list[S] = field(default_factory=list)
    id: str = ""
    description: str = ""

    # wired by EntityMeta when the lifecycle is used as a field default
    _entity_cls: type | None = field(default=None, repr=False, compare=False)
    _field_name: str = field(default="", repr=False, compare=False)

    def _bind(self, entity_cls: type, field_name: str) -> None:
        self._entity_cls = entity_cls
        self._field_name = field_name
        if not self.id:
            self.id = f"{entity_cls.__name__}.{field_name}"

    @property
    def entity_cls(self) -> type:
        if self._entity_cls is None:
            raise RuntimeError(f"lifecycle '{self.id}' is not attached to an entity field")
        return self._entity_cls

    @property
    def field_name(self) -> str:
        return self._field_name

    @property
    def field(self) -> FieldDescriptor:
        """The bound descriptor, exposed for read-only introspection."""
        from analint.models.entity import all_fields

        return all_fields(self.entity_cls)[self.field_name]

    def reachable_states(self) -> set[S]:
        """BFS from initial through transitions — returns all reachable states."""
        visited: set[S] = set()
        queue = [self.initial]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            for t in self.transitions:
                if t.from_state == cur:
                    for target in t.to_states:
                        if target not in visited:
                            queue.append(target)
        return visited
