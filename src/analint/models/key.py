"""State-independent scope identity as a closed value expression."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from analint.models.expr import Expr
from analint.models.scope import InstanceRef


@dataclass(eq=False)
class Key(Expr):
    """The declared key of an InstanceRef, instance Param or quantified Bound.

    Identity does not read state: even an absent slot has its declared key.
    Keys used as values must be JSON scalars or Enum members. Existing scopes
    with other hashable keys remain valid, but cannot use this expression.
    """

    target: Any

    def __post_init__(self) -> None:
        from analint.models.param import Param
        from analint.models.quantifier import Bound

        if isinstance(self.target, InstanceRef):
            refs = [self.target]
        elif isinstance(self.target, Bound):
            refs = list(self.target.scope)
        elif isinstance(self.target, Param) and all(
            isinstance(ref, InstanceRef) for ref in self.target.domain
        ):
            refs = self.target.domain
        else:
            raise TypeError("Key needs an InstanceRef, Bound, or instance Param")
        for ref in refs:
            if ref.scope._refs.get(ref.key) is not ref:
                raise TypeError("Key target must be a declared InstanceRef from its Scope")
            value = ref.key
            if not (
                value is None
                or isinstance(value, (bool, int, str, Enum))
                or (isinstance(value, float) and math.isfinite(value))
            ):
                raise TypeError("Key values must be JSON scalars or Enum members")

    def __repr__(self) -> str:
        return f"Key({self.target!r})"
