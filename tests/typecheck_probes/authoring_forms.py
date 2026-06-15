"""Type-check probes for documented authoring forms (P4.0a, research/27).

This file is NOT executed and NOT collected by pytest. It exists to be run through
a type checker (`ty check tests/typecheck_probes/authoring_forms.py`) by
``tests/test_typecheck_probes.py``, which preserves the resulting diagnostics as a
regression signal for the DSL's dual view (research/27 §2):

- *instance* access is honestly typed and must stay clean;
- *class-level* comparisons build a ``Predicate`` at runtime but the checker reads
  the source annotation and infers ``bool`` (metaclass opacity) — the dominant,
  ACCEPTED authoring diagnostic.

If these diagnostics disappear or change shape, the DSL's type surface changed —
investigate before updating the probe test.
"""

from __future__ import annotations

from analint import Action, Entity, Field, Invariant, Lifecycle, Param, Set, Transition


class WalletState(Entity):
    balance: int = Field(0, ge=0, le=100)


# Instance access is the honest domain view: this must remain correctly typed (int)
# and produce NO diagnostic.
def domain_value_is_typed(w: WalletState) -> int:
    return w.balance


# Class-level comparison: a Predicate at runtime, inferred `bool` by the checker.
# Passing it where a Predicate is expected reproduces the metaclass-opacity
# diagnostic (invalid-argument-type: Expected `Predicate`, found `bool`).
non_negative = Invariant(WalletState.balance >= 0)

credit = Action(
    pre=[WalletState.balance < 100],  # class-level comparison → Predicate vs bool
    effect=[Set(WalletState.balance, WalletState.balance + 1)],
)


# Advanced forms must be exercised too, so a future "fix" cannot quietly leave the
# advanced DSL untyped while only singleton fields improve.
class Phase(Entity):
    state: str = Lifecycle(
        initial="open",
        transitions=[Transition("open", ["closed"])],
        terminal=["closed"],
    )


amount = Param("amount", ge=1, le=3)
