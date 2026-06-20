from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analint.models.entity import FieldDescriptor


@dataclass
class Lifecycle[S]:
    """The lifecycle of an entity field, declared as the field's default value:

        class Card(Entity):
            status: CardStatus = Lifecycle(
                initial=CardStatus.TODO,
                transitions={CardStatus.TODO: [CardStatus.DONE]},
                terminal=[CardStatus.DONE],
            )

    The field's default value is `initial`. `terminal` states have no way out:
    an entity in a terminal state cannot be modified by any action.
    `entity_cls` and `field_name` are wired by the Entity metaclass.
    """

    initial: S
    transitions: Mapping[S, Iterable[S]] = field(default_factory=dict)
    terminal: list[S] = field(default_factory=list)
    id: str = ""
    description: str = ""

    # wired by EntityMeta when the lifecycle is used as a field default
    _entity_cls: type | None = field(default=None, repr=False, compare=False)
    _field_name: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.transitions, Mapping):
            raise TypeError("Lifecycle transitions must be a mapping of source: [targets]")
        normalized: dict[S, tuple[S, ...]] = {}
        for source, targets in self.transitions.items():
            if isinstance(targets, (str, bytes)) or not isinstance(targets, Iterable):
                raise TypeError(
                    f"Lifecycle transition targets must be a collection — write "
                    f"transitions={{{source!r}: [{targets!r}]}}"
                )
            normalized[source] = tuple(targets)
        self.transitions = normalized

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
            for target in self.transitions.get(cur, ()):
                if target not in visited:
                    queue.append(target)
        return visited
