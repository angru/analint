"""Negative type-check probes (P4.0b, research/27).

NOT executed and NOT collected by pytest. ``tests/test_typecheck_probes.py`` runs
``ty`` on this file and asserts the checker rejects clearly-wrong authoring.

Unlike class-level *field* access (which the checker cannot see through — the
accepted dual-view boundary), the DSL *constructors* have honestly typed
parameters (`Predicate`, field references), so passing the wrong kind of value is
caught. These probes prove that real authoring mistakes still fail static checking
even though the metaclass hides class-level field expressions.

Limit (research/27): a wrong *value* in a `Set` over a class-level field, or a
mistyped `Entity(...)` constructor field, is NOT caught today — entity
construction is dynamic `**kwargs`. That gap is documented, not asserted here.
"""

from __future__ import annotations

from analint import Invariant, Reachable, Unreachable

# A bare value is not a Predicate — the query/invariant constructors must reject it.
not_a_predicate_invariant = Invariant(5)  # ty: invalid-argument-type (int, not Predicate)
not_a_predicate_reachable = Reachable("done")  # ty: invalid-argument-type (str, not Predicate)
not_a_predicate_unreachable = Unreachable(42)  # ty: invalid-argument-type (int, not Predicate)
