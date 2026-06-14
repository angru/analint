"""State-level legality checks shared by the scenario and flow runners.

The transition kernel decides whether an action can fire and what the next state
is; it deliberately does not decide whether a *state* is legal. Invariants are a
predicate over a state, so every caller that produces states (a scenario's pre/
post, each accepted step of a flow) must check them — here, once, instead of
copying the logic per runner.
"""

from __future__ import annotations

from analint.models.root import Spec
from analint.models.scope import field_context_key
from analint.reporter.base import Finding, Severity
from analint.validator.rule_checker import evaluate
from analint.validator.structural import _collect_field_refs, _describe


def relevant_invariants(spec: Spec, context: dict) -> list:
    """Invariants whose referenced entities are all present in ``context`` — the
    only ones that can be meaningfully evaluated against this state."""
    return [
        inv
        for inv in spec.invariants
        if {field_context_key(ref) for ref in _collect_field_refs(inv.expression)} <= set(context)
    ]


def check_invariants(invariants: list, context: dict, label: str) -> list[Finding]:
    """Evaluate world invariants over one state; an empty result means all hold.
    A violation or an evaluation error is a model defect, never a rejection."""
    findings: list[Finding] = []
    for inv in invariants:
        text = inv.label or _describe(inv.expression)
        loc = f"invariant:{inv.id}"
        try:
            if not evaluate(inv.expression, context):
                findings.append(Finding(Severity.ERROR, loc, f"{label} failed: {text}"))
        except Exception as exc:
            findings.append(Finding(Severity.ERROR, loc, f"evaluation error: {exc}"))
    return findings
