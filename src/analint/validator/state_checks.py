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


def invariant_is_applicable(inv: Invariant, context: dict) -> bool:
    """An invariant is applicable in this state only when every referenced entity
    is present — its key is in the context and (for a Scope slot) not absent.

    The single source of truth for presence-aware applicability, shared by the
    scenario/flow state checks, the explorer's per-state check and the canonical
    invariant scanner, so they can never diverge (review 8cca900)."""
    keys = _invariant_keys(inv, context)
    if any(key not in context for key in keys):
        return False
    return not any(isinstance(key, InstanceRef) and not is_present(context, key) for key in keys)


def _invariant_keys(inv: Invariant, context: dict) -> frozenset:
    # Keep the static fast path. Quantified/aggregate members depend on presence;
    # their required keys must be re-derived in each state. Compare the whole
    # universe with an empty one once to detect that dependency, and invalidate
    # both plans when the expression is reassigned.
    cached = inv.__dict__.get("_analint_keys")
    if cached is None or cached[0] is not inv.expression:
        keys = frozenset(field_context_key(ref) for ref in _collect_field_refs(inv.expression))
        free = frozenset(field_context_key(ref) for ref in _collect_field_refs(inv.expression, {}))
        cached = (inv.expression, keys, keys != free)
        inv.__dict__["_analint_keys"] = cached
    if cached[2]:
        # Field values do not change applicability. Reuse the last presence
        # layout, without retaining an unbounded cache of all slot subsets.
        signature = (
            frozenset(
                key for key in context if isinstance(key, InstanceRef) and is_present(context, key)
            ),
            cached[1] - context.keys(),
        )
        dynamic = inv.__dict__.get("_analint_present_keys")
        if dynamic is None or dynamic[0] is not inv.expression or dynamic[1] != signature:
            keys = frozenset(
                field_context_key(ref) for ref in _collect_field_refs(inv.expression, context)
            )
            dynamic = (inv.expression, signature, keys)
            inv.__dict__["_analint_present_keys"] = dynamic
        return dynamic[2]
    return cached[1]


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
                findings.append(Finding(Severity.ERROR, loc, f"{label} failed: {text}"))
        except Exception as exc:
            findings.append(Finding(Severity.ERROR, loc, f"evaluation error: {exc}"))
    return findings
