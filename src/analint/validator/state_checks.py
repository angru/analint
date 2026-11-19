"""State-level legality checks shared by the scenario and flow runners.

The transition kernel decides whether an action can fire and what the next state
is; it deliberately does not decide whether a *state* is legal. Invariants are a
predicate over a state, so every caller that produces states (a scenario's pre/
post, each accepted step of a flow) must check them — here, once, instead of
copying the logic per runner.

Applicability is presence-aware and recomputed per state: an invariant whose
referenced entity is absent (a Scope slot stores ``Absent(ref)`` under its key,
so a key in the context does not mean the entity is present) is not applicable.
``Create`` makes such an invariant applicable; ``Delete`` makes it inapplicable
again — so callers must re-evaluate against each state, not a precomputed list.
"""

from __future__ import annotations

from collections.abc import Callable

from analint.models.invariant import Invariant
from analint.models.root import Spec
from analint.models.scope import (
    Absent,
    InstanceRef,
    field_context_key,
    instance_context_key,
    is_present,
)
from analint.reporter.base import Code, Finding, Severity
from analint.validator.rule_checker import compile_predicate, evaluate
from analint.validator.structural import _collect_field_refs, _describe


def build_snapshot_context(spec: Spec, given: list) -> dict:
    """The shared initial context for a scenario or flow: the ``given`` snapshots
    keyed by instance, with every unspecified Scope slot absent. A partial
    snapshot — entities not listed (and not a Scope slot) are simply not present,
    so an action that needs one is rejected. This is NOT the canonical
    defaults-built world (which makes default-constructible Scope slots present);
    scenario and flow share exactly this builder so their worlds match."""
    context = {instance_context_key(inst): inst for inst in given}
    for scope in spec.scopes:
        for ref in scope:
            context.setdefault(ref, Absent(ref))
    return context


class InvariantPlan:
    """Derived checks owned by one synchronous exploration or invariant scan.

    Declarations, including nested expressions and lists, remain editable
    between runs. Never attach compiled closures or reference sets to them:
    expression identity cannot detect nested edits, and deepcopy retains the
    original closure's captured objects. Callers reuse a plan only while the
    model is unchanged within their scan.
    """

    def __init__(self, inv: Invariant) -> None:
        self.expression = inv.expression
        self._compiled: Callable[[dict], bool] | None = None
        self._keys = frozenset(
            field_context_key(ref) for ref in _collect_field_refs(self.expression)
        )
        none_present = {key: Absent(key) for key in self._keys if isinstance(key, InstanceRef)}
        free = frozenset(
            field_context_key(ref) for ref in _collect_field_refs(self.expression, none_present)
        )
        self._presence_dependent = self._keys != free
        self._present_keys: tuple[tuple[frozenset, frozenset], frozenset] | None = None

    def holds(self, context: dict) -> bool:
        # Compile lazily inside the caller's evaluation-error boundary, and
        # only if the invariant applies to at least one state.
        if self._compiled is None:
            self._compiled = compile_predicate(self.expression)
        return self._compiled(context)

    def is_applicable(self, context: dict) -> bool:
        keys = self._required_keys(context)
        if any(key not in context for key in keys):
            return False
        return not any(
            isinstance(key, InstanceRef) and not is_present(context, key) for key in keys
        )

    def _required_keys(self, context: dict) -> frozenset:
        if not self._presence_dependent:
            return self._keys
        # Quantified/aggregate members depend on presence. Reuse only the last
        # layout, without retaining an unbounded cache of all slot subsets.
        signature = (
            frozenset(
                key for key in context if isinstance(key, InstanceRef) and is_present(context, key)
            ),
            self._keys - context.keys(),
        )
        if self._present_keys is None or self._present_keys[0] != signature:
            keys = frozenset(
                field_context_key(ref) for ref in _collect_field_refs(self.expression, context)
            )
            self._present_keys = (signature, keys)
        return self._present_keys[1]


def invariant_is_applicable(inv: Invariant, context: dict) -> bool:
    """An invariant is applicable in this state only when every referenced entity
    is present — its key is in the context and (for a Scope slot) not absent.

    The single source of truth for presence-aware applicability, shared by the
    scenario/flow state checks, the explorer's per-state check and the canonical
    invariant scanner, so they can never diverge (review 8cca900)."""
    return InvariantPlan(inv).is_applicable(context)


def applicable_invariants(spec: Spec, context: dict) -> list:
    """The invariants that can be meaningfully evaluated against this state."""
    return [inv for inv in spec.invariants if invariant_is_applicable(inv, context)]


def check_invariants(spec: Spec, context: dict, label: str) -> list[Finding]:
    """Evaluate every applicable world invariant over one state; an empty result
    means all hold. A violation or an evaluation error is a model defect."""
    findings: list[Finding] = []
    for inv in spec.invariants:
        if not invariant_is_applicable(inv, context):
            continue
        text = inv.label or _describe(inv.expression)
        loc = f"invariant:{inv.id}"
        try:
            if not evaluate(inv.expression, context):
                findings.append(
                    Finding(Severity.ERROR, loc, f"{label} failed: {text}", Code.INVARIANT_VIOLATED)
                )
        except Exception as exc:
            findings.append(
                Finding(
                    Severity.ERROR, loc, f"evaluation error: {exc}", Code.INVARIANT_EVALUATION_ERROR
                )
            )
    return findings
