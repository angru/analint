from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Transition:
    """One allowed state transition for an entity field.

    from_state  — source state (enum value).
    to_states   — single target or list of targets.

    Examples::

        Transition(PENDING, PAID)
        Transition(PENDING, [PAID, CANCELLED])
    """
    from_state: object
    to_states: object  # single value or list — normalised to list in __post_init__

    def __post_init__(self) -> None:
        if not isinstance(self.to_states, list):
            self.to_states = [self.to_states]


@dataclass
class StateMachine:
    """Describes the lifecycle of one entity field.

    field   — FieldDescriptor, e.g. Order.status
    initial — initial value when entity is created
    transitions — allowed transitions
    """
    id: str
    field: object          # FieldDescriptor
    initial: object        # enum value
    transitions: list[Transition] = field(default_factory=list)
    description: str = ""

    @property
    def entity_cls(self) -> type:
        return self.field.entity_cls  # type: ignore[attr-defined]

    @property
    def field_name(self) -> str:
        return self.field.field_name  # type: ignore[attr-defined]

    def reachable_states(self) -> set:
        """BFS from initial through transitions — returns all reachable states."""
        visited: set = set()
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
