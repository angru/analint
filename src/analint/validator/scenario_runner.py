from __future__ import annotations

from typing import Any

from analint.models.flow import Assert, Emitted
from analint.models.predicate import Predicate
from analint.models.root import Spec
from analint.models.scenario import Expect, Scenario
from analint.models.scope import Absent, field_context_key, instance_context_key
from analint.reporter.base import Finding, ScenarioResult, Severity
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.structural import _collect_field_refs, _describe


def run_scenario(scenario: Scenario, spec: Spec) -> ScenarioResult:
    """Run one scenario through the shared transition kernel.

    The kernel decides the transition; this wrapper layers the scenario's own
    concerns on top: the *pre-state* must be a legal world (invariants hold),
    the *post-state* must keep holding them, and any ``then`` assertions must be
    satisfied. ``Expect.FAIL`` is honoured only for a genuine pre-execution
    block — never for a model defect.
    """
    findings: list[Finding] = []
    context = {instance_context_key(inst): inst for inst in scenario.given}
    for scope in spec.scopes:
        for ref in scope:
            context.setdefault(ref, Absent(ref))
    action = scenario.action

    relevant_invariants = [
        inv for inv in spec.invariants if _referenced_keys(inv.expression) <= set(context)
    ]
    checks_count = len(relevant_invariants) + len(action.pre) + len(action.post)

    # The pre-state's world invariants. A violation here blocks the action
    # before it runs, which Expect.FAIL legitimises — exactly as before. (The
    # kernel is set to tighten this to a model defect; that change is gated by
    # test_transition_conformance and is not part of this migration.)
    pre_invariant_violated = _check_invariants(findings, relevant_invariants, context, "INVARIANT")

    # The transition itself: pre/presence/terminal guards, effects, Field,
    # lifecycle and postconditions all live in the kernel now.
    result = step(spec, action, context)
    findings.extend(result.findings)

    post_defect = False
    if result.outcome is Outcome.ACCEPTED and not pre_invariant_violated:
        post = result.post_context
        assert post is not None
        post_defect = _check_invariants(findings, relevant_invariants, post, "INVARIANT (post)")
        post_defect = _check_then(findings, scenario, post) or post_defect

    # A pre-execution block — a guard rejection or a failed pre-state invariant —
    # is the only thing Expect.FAIL may legitimise; a model defect never is.
    pre_block = result.outcome is Outcome.REJECTED or pre_invariant_violated

    if scenario.expected == Expect.FAIL:
        passed = pre_block
        if passed:
            findings.append(
                Finding(
                    Severity.INFO,
                    f"scenario:{scenario.id}",
                    "correctly blocked — rules rejected this data as expected",
                )
            )
        else:
            message = "expected the action to be blocked, but every precondition passed"
            if result.outcome is Outcome.DEFECT or post_defect:
                message += " — the failures above are a model defect, not a rejection"
            findings.append(Finding(Severity.ERROR, f"scenario:{scenario.id}", message))
    else:
        passed = (
            result.outcome is Outcome.ACCEPTED and not pre_invariant_violated and not post_defect
        )

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=passed,
        findings=findings,
        rules_count=checks_count,
    )


def _check_invariants(findings: list[Finding], invariants: list, context: dict, label: str) -> bool:
    """Evaluate world invariants over one state; True if any is violated."""
    violated = False
    for inv in invariants:
        text = inv.label or _describe(inv.expression)
        loc = f"invariant:{inv.id}"
        try:
            if not evaluate(inv.expression, context):
                findings.append(Finding(Severity.ERROR, loc, f"{label} failed: {text}"))
                violated = True
        except Exception as exc:
            findings.append(Finding(Severity.ERROR, loc, f"evaluation error: {exc}"))
            violated = True
    return violated


def _check_then(findings: list[Finding], scenario: Scenario, post: dict) -> bool:
    """Evaluate the scenario's ``then`` assertions over the next state."""
    emitted_names = {
        (e if isinstance(e, type) else type(e)).__name__ for e in scenario.action.emits
    }
    failed = False
    for assertion in scenario.then:
        if isinstance(assertion, Assert):
            try:
                if not evaluate(assertion.predicate, post):
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            f"scenario:{scenario.id}",
                            f"then: {_describe(assertion.predicate)} — not satisfied",
                        )
                    )
                    failed = True
            except Exception as exc:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then evaluation error: {exc}",
                    )
                )
                failed = True
        elif isinstance(assertion, Emitted):
            if assertion.event_cls.__name__ not in emitted_names:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then: event '{assertion.event_cls.__name__}' not in action.emits",
                    )
                )
                failed = True
        else:
            findings.append(
                Finding(
                    Severity.ERROR,
                    f"scenario:{scenario.id}",
                    f"then entry '{assertion!r}' is not Assert(...) or Emitted(...)",
                )
            )
            failed = True
    return failed


def _referenced_keys(pred: Predicate) -> set[Any]:
    return {field_context_key(ref) for ref in _collect_field_refs(pred)}
