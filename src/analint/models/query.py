from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Reachable:
    """The predicate must hold in at least one state reachable from the initial one.

    The initial state is built from entity field defaults; `given` overrides
    or supplies instances (required for entities without full defaults).
    Passing produces a witness trace — the sequence of actions leading there.
    """
    predicate: object
    given: list = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class Unreachable:
    """The system must never be able to reach a state where the predicate holds.

    A regression guard: if a later change makes the state reachable, the query
    fails with a counterexample trace.
    """
    predicate: object
    given: list = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class AlwaysHolds:
    """The predicate must hold in every reachable state (a checked invariant
    over the whole state space, not just over scenario snapshots)."""
    predicate: object
    given: list = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class NoDeadEnd:
    """From every reachable state, `goal` must still be achievable.

    The classic softlock detector: fails with a trace to the first reachable
    state from which no path to the goal exists.
    """
    goal: object
    given: list = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class DeadActions:
    """Report actions that are never enabled in any reachable state."""
    given: list = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class Bounds:
    """Declared range for a numeric field — keeps the state space finite.

    Default: an effect that drives the field outside [min, max] is an error
    finding and the branch is pruned. With `saturate=True` the value clamps
    to the range instead (use for counters where only thresholds matter,
    e.g. "disturbed at most twice").
    """
    field: object   # FieldDescriptor
    min: object
    max: object
    saturate: bool = False
    id: str = ""


QUERY_TYPES = (Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions)
