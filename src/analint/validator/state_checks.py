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

from analint.models.invariant import Invariant
from analint.models.root import Spec
from analint.models.scope import (
    Absent,
    InstanceRef,
    field_context_key,
    instance_context_key,
    is_present,
)
from analint.reporter.base import Finding, Severity
from analint.validator.rule_checker import evaluate
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


def _applicable(inv: Invariant, context: dict) -> bool:
    """An invariant is applicable in this state only when every referenced entity
    is present — its key is in the context and (for a Scope slot) not absent."""
    keys = {field_context_key(ref) for ref in _collect_field_refs(inv.expression)}
    if not keys <= set(context):
        return False
    return not any(isinstance(key, InstanceRef) and not is_present(context, key) for key in keys)


def applicable_invariants(spec: Spec, context: dict) -> list:
    """The invariants that can be meaningfully evaluated against this state."""
    return [inv for inv in spec.invariants if _applicable(inv, context)]


def check_invariants(spec: Spec, context: dict, label: str) -> list[Finding]:
    """Evaluate every applicable world invariant over one state; an empty result
    means all hold. A violation or an evaluation error is a model defect."""
    findings: list[Finding] = []
    for inv in applicable_invariants(spec, context):
        text = inv.label or _describe(inv.expression)
        loc = f"invariant:{inv.id}"
        try:
            if not evaluate(inv.expression, context):
                findings.append(Finding(Severity.ERROR, loc, f"{label} failed: {text}"))
        except Exception as exc:
            findings.append(Finding(Severity.ERROR, loc, f"evaluation error: {exc}"))
    return findings
