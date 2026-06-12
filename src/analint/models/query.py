from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from analint.models.predicate import Predicate


@dataclass
class Reachable:
    """The predicate must hold in at least one state reachable from the initial one.

    The initial state is built from entity field defaults; `given` overrides
    or supplies instances (required for entities without full defaults).
    `given_any=[[...], [...]]` declares a finite SET of admissible initial
    states — the verdict then quantifies over every one of them (research/16).
    Passing produces a witness trace — the sequence of actions leading there.
    """

    predicate: Predicate
    given: list[Any] = field(default_factory=list)
    given_any: list[list[Any]] = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class Unreachable:
    """The system must never be able to reach a state where the predicate holds.

    A regression guard: if a later change makes the state reachable, the query
    fails with a counterexample trace.
    """

    predicate: Predicate
    given: list[Any] = field(default_factory=list)
    given_any: list[list[Any]] = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class AlwaysHolds:
    """The predicate must hold in every reachable state (a checked invariant
    over the whole state space, not just over scenario snapshots)."""

    predicate: Predicate
    given: list[Any] = field(default_factory=list)
    given_any: list[list[Any]] = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class NoDeadEnd:
    """From every reachable state, `goal` must still be achievable.

    The classic softlock detector: fails with a trace to the first reachable
    state from which no path to the goal exists.
    """

    goal: Predicate
    given: list[Any] = field(default_factory=list)
    given_any: list[list[Any]] = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


@dataclass
class DeadActions:
    """Report actions that are never enabled in any reachable state."""

    given: list[Any] = field(default_factory=list)
    given_any: list[list[Any]] = field(default_factory=list)
    id: str = ""
    label: str = ""
    max_states: int = 10_000


QUERY_TYPES = (Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions)
