"""Declarative finite relations for reachability initial states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from analint.models.predicate import Predicate, normalize_predicate


@dataclass
class Initial:
    """Generate admissible initial states from finite field domains.

    ``vary`` contains concrete fields or ``BoundField`` values. ``where``
    filters their Cartesian product with ordinary predicate AST nodes.
    ``given`` fixes fields and supplies entities without defaults.
    """

    vary: list[Any]
    where: list[Predicate] = field(default_factory=list)
    given: list[Any] = field(default_factory=list)
    max_candidates: int = 10_000

    def __post_init__(self) -> None:
        self.where = [normalize_predicate(predicate) for predicate in self.where]
        if not self.vary:
            raise TypeError("Initial vary= needs at least one field")
        if not isinstance(self.max_candidates, int) or self.max_candidates <= 0:
            raise TypeError("Initial max_candidates must be a positive integer")
