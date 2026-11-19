"""An explicit boolean value computed by the predicate evaluator."""

from dataclasses import dataclass

from analint.models.expr import Expr
from analint.models.predicate import Predicate, normalize_predicate


@dataclass(eq=False)
class BoolValue(Expr):
    """Use a DSL predicate as a value, for example on an effect's right side.

    This does not coerce host-Python truthiness. The predicate is evaluated in
    the operand's context; effect operands therefore read the pre-state.
    """

    predicate: Predicate

    def __post_init__(self) -> None:
        self.predicate = normalize_predicate(self.predicate)
        if not isinstance(self.predicate, Predicate):
            raise TypeError("BoolValue needs a DSL predicate or boolean field reference")
